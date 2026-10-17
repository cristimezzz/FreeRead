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
