import httpx
import pytest

from freeread.infra.zotero.local_api import LocalApiConnector, ZoteroUnavailableError

ITEMS = [
    {
        "key": "PAPER001",
        "version": 7,
        "data": {
            "itemType": "journalArticle",
            "title": "A Paper",
            "creators": [{"creatorType": "author", "firstName": "A", "lastName": "B"}],
            "date": "2021-07-15",
            "DOI": "10.1/x",
            "collections": ["COLL0001"],
            "tags": [{"tag": "ml"}],
            "language": "en",
        },
    },
    {"key": "NOTE0001", "version": 3, "data": {"itemType": "note", "note": "x"}},
]


def attachments(tmp_path):
    pdf = tmp_path / "storage" / "ATT00001" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4")
    return [
        {
            "key": "ATT00001",
            "version": 7,
            "links": {"enclosure": {"href": pdf.as_uri(), "type": "application/pdf"}},
            "data": {
                "itemType": "attachment",
                "parentItem": "PAPER001",
                "contentType": "application/pdf",
                "filename": "paper.pdf",
                "linkMode": "imported_file",
                "path": "storage:paper.pdf",
            },
        },
        {
            "key": "ATT00002",
            "version": 7,
            "data": {
                "itemType": "attachment",
                "parentItem": "PAPER001",
                "contentType": "application/pdf",
                "filename": "missing.pdf",
                "linkMode": "imported_file",
            },
        },
    ]


def make_transport(tmp_path, seen: list):
    atts = attachments(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        path = request.url.path
        if path.endswith("/collections"):
            rows = [{"key": "COLL0001", "data": {"name": "论文", "parentCollection": False}}]
        elif path.endswith("/items"):
            t = request.url.params.get("itemType")
            rows = atts if t == "attachment" else ITEMS
        else:
            return httpx.Response(404)
        start = int(request.url.params.get("start", 0))
        return httpx.Response(200, json=rows[start:], headers={"Total-Results": str(len(rows))})

    return httpx.MockTransport(handler)


async def test_lists_collections_items_and_resolves_pdf(tmp_path):
    seen: list = []
    async with LocalApiConnector(
        base_url="http://zotero.test/api/users/0/",
        data_dir=tmp_path,
        transport=make_transport(tmp_path, seen),
    ) as z:
        cols = await z.list_collections()
        assert [(c.key, c.name, c.parent_key) for c in cols] == [("COLL0001", "论文", None)]

        items = await z.list_items()
        assert [i.key for i in items] == ["PAPER001"]  # note 被过滤
        item = items[0]
        assert item.year == 2021 and item.doi == "10.1/x" and item.tags == ["ml"]
        assert [a.key for a in item.attachments] == ["ATT00001", "ATT00002"]

        resolved = await z.resolve_attachment(item, item.attachments[0])
        assert resolved == tmp_path / "storage" / "ATT00001" / "paper.pdf"
        assert await z.resolve_attachment(item, item.attachments[1]) is None


async def test_falls_back_to_storage_dir_without_href(tmp_path):
    seen: list = []
    async with LocalApiConnector(
        base_url="http://zotero.test/api/users/0/",
        data_dir=tmp_path,
        transport=make_transport(tmp_path, seen),
    ) as z:
        item = (await z.list_items())[0]
        att = item.attachments[0]
        att.href = None
        assert (await z.resolve_attachment(item, att)).name == "paper.pdf"


async def test_unavailable_gives_clear_error():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    async with LocalApiConnector(transport=httpx.MockTransport(refuse)) as z:
        with pytest.raises(ZoteroUnavailableError):
            await z.list_collections()


async def test_standalone_pdf_venue_and_library_version(tmp_path):
    rows = {
        "items": [
            {
                "key": "PAPER002",
                "version": 9,
                "data": {
                    "itemType": "conferencePaper",
                    "title": "Conf Paper",
                    "proceedingsTitle": "Proceedings of ACL",
                },
            }
        ],
        "attachments": [
            {
                "key": "SOLO0001",
                "version": 8,
                "data": {
                    "itemType": "attachment",
                    "title": "译文副本",
                    "contentType": "application/pdf",
                    "filename": "copy.pdf",
                    "collections": ["COLL0001"],
                    "tags": [{"tag": "zh"}],
                },
            },
            {
                "key": "SNAP0001",
                "version": 8,
                "data": {"itemType": "attachment", "contentType": "text/html"},
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        t = request.url.params.get("itemType")
        data = rows["attachments"] if t == "attachment" else rows["items"]
        return httpx.Response(
            200,
            json=data,
            headers={"Total-Results": str(len(data)), "Last-Modified-Version": "123"},
        )

    async with LocalApiConnector(
        base_url="http://zotero.test/api/users/0/",
        data_dir=tmp_path,
        transport=httpx.MockTransport(handler),
    ) as z:
        items = await z.list_items()
        assert z.library_version == 123

    paper, solo = items  # 非 PDF 的独立附件（网页快照）被忽略
    assert paper.venue == "Proceedings of ACL"
    assert (solo.key, solo.item_type, solo.title) == ("SOLO0001", "attachment", "译文副本")
    assert solo.collection_keys == ["COLL0001"] and solo.tags == ["zh"]
    assert solo.extra == {"standalone": True}
    assert [a.key for a in solo.attachments] == ["SOLO0001"]


async def test_incremental_items_fetch_parents_of_changed_attachments(tmp_path):
    """since 只作用于普通条目；只变了附件的条目按 itemKey 补读，并带上完整附件列表。"""
    atts = attachments(tmp_path)
    atts[1]["version"] = 9  # 只有这个附件在版本 8 之后变了
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        p = request.url.params
        if p.get("format") == "versions":
            keys = {r["key"]: r["version"] for r in [*ITEMS, *atts]}
            return httpx.Response(200, json=keys, headers={"Total-Results": str(len(keys))})
        if p.get("itemType") == "attachment":
            rows = atts
        elif p.get("itemKey"):
            rows = [r for r in ITEMS if r["key"] in p["itemKey"].split(",")]
        else:
            rows = [r for r in ITEMS if r["version"] > int(p.get("since", -1))]
        return httpx.Response(
            200, json=rows, headers={"Total-Results": str(len(rows)), "Last-Modified-Version": "9"}
        )

    async with LocalApiConnector(
        base_url="http://zotero.test/api/users/0/",
        data_dir=tmp_path,
        transport=httpx.MockTransport(handler),
    ) as c:
        items = await c.list_items(since_version=8)
        assert [i.key for i in items] == ["PAPER001"]
        assert [a.key for a in items[0].attachments] == ["ATT00001", "ATT00002"]
        assert any(u.params.get("itemKey") == "PAPER001" for u in seen)
        assert (
            next(u for u in seen if u.params.get("itemType") == "attachment").params.get("since")
            is None
        )
        assert await c.list_keys() == {"PAPER001", "NOTE0001", "ATT00001", "ATT00002"}
        assert c.library_version == 9


async def test_list_keys_unsupported_or_truncated(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("format") == "versions":
            return httpx.Response(200, json={"A": 1}, headers={"Total-Results": "2"})
        return httpx.Response(404)

    async with LocalApiConnector(
        base_url="http://zotero.test/api/users/0/",
        transport=httpx.MockTransport(handler),
    ) as c:
        assert await c.list_keys() is None  # 被截断
