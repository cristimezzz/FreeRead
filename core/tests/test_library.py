import time
from pathlib import Path

import pytest

from freeread.infra.db.models import (
    AttachmentRow,
    CollectionRow,
    DocumentRow,
    ItemCollectionRow,
    ItemRow,
    SyncStateRow,
)
from freeread.infra.jobs.queue import JobStatus
from freeread.infra.zotero.base import Attachment, Collection, Item
from freeread.infra.zotero.local_api import ZoteroUnavailableError
from freeread.services import library as library_mod
from freeread.services.library import InvalidImportError, doc_id_for, sha256_file


def write_pdf(path: Path, body: str, title: str | None = None) -> Path:
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), body)
    if title:
        doc.set_metadata({"title": title})
    doc.save(path)
    doc.close()
    return path


class FakeConnector:
    def __init__(self, collections, items, files, version=42):
        self.collections, self.items, self.files = collections, items, files
        self.library_version = version
        self.closed = False

    async def list_collections(self):
        return self.collections

    async def list_items(self, since_version=None):
        return self.items

    async def resolve_attachment(self, item, attachment):
        return self.files.get(attachment.key)

    async def aclose(self):
        self.closed = True


def pdf_att(key):
    return Attachment(key=key, content_type="application/pdf", filename=f"{key}.pdf")


@pytest.fixture
def zotero(tmp_path):
    """分类：ROOT ⊃ CHILD，OTHER；条目：A ∈ ROOT，B ∈ CHILD，C ∈ OTHER，S 为独立 PDF。"""
    files = {
        k: write_pdf(tmp_path / "zotero" / f"{k}.pdf", f"paper {k}")
        for k in ("ATT_A", "ATT_B", "ATT_C", "ATT_S")
    }
    collections = [
        Collection("ROOT", "机器学习"),
        Collection("CHILD", "翻译", parent_key="ROOT"),
        Collection("OTHER", "其他"),
    ]
    items = [
        Item(
            key="A",
            version=1,
            item_type="journalArticle",
            title="Attention Is All You Need",
            creators=[
                {"creatorType": "author", "firstName": "Ashish", "lastName": "Vaswani"},
                {"creatorType": "author", "name": "Google Brain"},
            ],
            year=2017,
            venue="NeurIPS",
            collection_keys=["ROOT"],
            tags=["transformer", "transformer"],
            attachments=[pdf_att("ATT_A"), Attachment("NOTE_HTML", "text/html")],
            extra={"language": "en"},
        ),
        Item(
            key="B",
            version=1,
            item_type="preprint",
            title="Neural Machine Translation",
            collection_keys=["CHILD"],
            attachments=[pdf_att("ATT_B")],
        ),
        Item(
            key="C",
            version=1,
            item_type="book",
            title="Other Topic",
            collection_keys=["OTHER"],
            attachments=[pdf_att("ATT_C"), pdf_att("ATT_GONE")],
        ),
        Item(
            key="S",
            version=1,
            item_type="attachment",
            title="scan.pdf",
            attachments=[pdf_att("ATT_S")],
            extra={"standalone": True},
        ),
    ]
    return FakeConnector(collections, items, files)


def use(ctx, connector):
    ctx.library.connector_factory = lambda: connector
    return connector


def parse_jobs(ctx):
    return {
        j.payload["doc_id"] for j in ctx.jobs.list([JobStatus.QUEUED], kind="parse", limit=1000)
    }


async def test_full_sync_imports_everything(ctx, zotero):
    use(ctx, zotero)
    result = await ctx.library.sync_zotero()

    assert (result.added, result.updated, result.archived) == (4, 0, 0)
    assert result.collections == 3 and result.missing_files == 1
    assert zotero.closed
    assert len(parse_jobs(ctx)) == 4

    with ctx.sessions() as s:
        a = s.query(ItemRow).filter_by(zotero_key="A").one()
        assert a.authors == [
            {"first": "Ashish", "last": "Vaswani", "type": "author"},
            {"name": "Google Brain", "type": "author"},
        ]
        assert a.venue == "NeurIPS" and a.extra == {"language": "en"}
        assert s.query(SyncStateRow).one().last_version == 42
        assert s.query(DocumentRow).count() == 4
        sha = sha256_file(zotero.files["ATT_A"])
        att = s.query(AttachmentRow).filter_by(zotero_key="ATT_A").one()
        assert att.sha256 == sha and att.doc_id == doc_id_for(sha)

    detail = ctx.library.get_item(a.id)
    assert detail.tags == ["transformer"]
    assert [d.parse_status for d in detail.documents] == ["pending"]
    standalone = ctx.library.list_items(q="scan").items[0]
    assert standalone.item_type == "attachment"


async def test_collection_scope_includes_subcollections(ctx, zotero):
    use(ctx, zotero)
    await ctx.library.sync_zotero("ROOT")
    expected = {doc_id_for(sha256_file(zotero.files[k])) for k in ("ATT_A", "ATT_B")}
    assert parse_jobs(ctx) == expected
    # 元数据仍是全量
    assert ctx.library.list_items().total == 4


async def test_unknown_collection_is_rejected(ctx, zotero):
    use(ctx, zotero)
    with pytest.raises(ValueError, match="NOPE"):
        await ctx.library.sync_zotero("NOPE")


async def test_resync_archives_missing_reuses_hashes_and_no_duplicate_jobs(
    ctx, zotero, monkeypatch
):
    use(ctx, zotero)
    await ctx.library.sync_zotero()
    jobs_before = parse_jobs(ctx)

    zotero.items = [i for i in zotero.items if i.key != "C"]
    zotero.items[0].title = "Attention Is All You Need (v2)"
    zotero.items[0].version = 2
    zotero.collections = [c for c in zotero.collections if c.key != "OTHER"]
    hashed = []
    monkeypatch.setattr(library_mod, "sha256_file", lambda p: hashed.append(p) or sha256_file(p))
    result = await ctx.library.sync_zotero()

    assert hashed == []
    assert (result.added, result.updated, result.archived) == (0, 1, 1)
    assert result.parse_jobs == [] and parse_jobs(ctx) == jobs_before
    assert ctx.library.list_items(status="archived").items[0].title == "Other Topic"
    assert {c.zotero_key for c in ctx.library.list_collections()} == {"ROOT", "CHILD"}

    # 条目在 Zotero 里恢复后重新变为 active
    zotero.items.append(Item(key="C", version=3, item_type="book", title="Other Topic"))
    result = await ctx.library.sync_zotero()
    assert result.updated == 1 and ctx.library.list_items(status="archived").total == 0


async def test_same_pdf_in_two_items_is_one_document(ctx, zotero, tmp_path):
    copy = tmp_path / "zotero" / "copy.pdf"
    copy.write_bytes(zotero.files["ATT_A"].read_bytes())
    zotero.files["ATT_DUP"] = copy
    zotero.items[1].attachments.append(pdf_att("ATT_DUP"))
    use(ctx, zotero)
    await ctx.library.sync_zotero()
    with ctx.sessions() as s:
        assert s.query(DocumentRow).count() == 4
        docs = {
            a.doc_id
            for a in s.query(AttachmentRow).filter(
                AttachmentRow.zotero_key.in_(["ATT_A", "ATT_DUP"])
            )
        }
    assert len(docs) == 1


async def test_item_with_several_pdfs_and_deleting_one(ctx, zotero, tmp_path):
    zotero.files["ATT_A2"] = write_pdf(tmp_path / "zotero" / "ATT_A2.pdf", "supplement A")
    zotero.items[0].attachments.append(pdf_att("ATT_A2"))
    use(ctx, zotero)
    await ctx.library.sync_zotero()
    item_id = ctx.library.list_items(q="Attention").items[0].id
    docs = ctx.library.get_item(item_id).documents
    assert [d.filename for d in docs] == ["ATT_A.pdf", "ATT_A2.pdf"]
    assert len({d.doc_id for d in docs}) == 2 and all(d.file_exists for d in docs)

    # 在 Zotero 里删除其中一个 PDF：同步前标记文件不存在，同步后从条目中移除
    zotero.files.pop("ATT_A").unlink()
    zotero.items[0].attachments = [pdf_att("ATT_A2")]
    assert [d.file_exists for d in ctx.library.get_item(item_id).documents] == [False, True]
    result = await ctx.library.sync_zotero()
    assert result.removed_files == 1
    docs = ctx.library.get_item(item_id).documents
    assert [d.filename for d in docs] == ["ATT_A2.pdf"]
    assert ctx.parse.pdf_path(docs[0].doc_id) == zotero.files["ATT_A2"]


async def test_listing_filters_search_and_counts(ctx, zotero):
    use(ctx, zotero)
    await ctx.library.sync_zotero()
    cols = {c.zotero_key: c for c in ctx.library.list_collections()}
    assert cols["CHILD"].parent_id == cols["ROOT"].id
    assert cols["ROOT"].item_count == 1  # 只算直接属于的条目

    root_items = ctx.library.list_items(collection_id=cols["ROOT"].id)
    assert [i.title for i in root_items.items] == ["Attention Is All You Need"]
    assert ctx.library.list_items(q="vaswani").total == 1  # 作者
    assert ctx.library.list_items(q="100%").total == 0  # LIKE 通配符被转义
    titles = [i.title for i in ctx.library.list_items(sort="title").items]
    assert titles == sorted(titles)
    page = ctx.library.list_items(sort="title", offset=1, limit=2)
    assert page.total == 4 and len(page.items) == 2


async def test_search_matches_non_ascii_authors(ctx, zotero):
    zotero.items[0].creators.append({"creatorType": "author", "firstName": "三", "lastName": "张"})
    use(ctx, zotero)
    await ctx.library.sync_zotero()
    assert ctx.library.list_items(q="张").total == 1


async def test_import_file_copies_and_dedupes(ctx, tmp_path):
    src = write_pdf(tmp_path / "in" / "my-paper.pdf", "hello", title="A Study of Things")
    item_id, created = ctx.library.import_file(src)
    assert created
    item = ctx.library.get_item(item_id)
    assert item.title == "A Study of Things" and item.zotero_key is None
    doc_id = item.documents[0].doc_id
    assert (ctx.paths.document_dir(doc_id) / "source.pdf").read_bytes() == src.read_bytes()
    assert parse_jobs(ctx) == {doc_id}

    again, created = ctx.library.import_file(src)
    assert (again, created) == (item_id, False)
    assert len(ctx.jobs.list(kind="parse")) == 1


async def test_import_file_title_falls_back_to_filename(ctx, tmp_path):
    src = write_pdf(tmp_path / "Smith2020 - Deep Things.pdf", "x", title="Microsoft Word - a.docx")
    item_id, _ = ctx.library.import_file(src)
    assert ctx.library.get_item(item_id).title == "Smith2020 - Deep Things"


def test_import_file_rejects_non_pdf(ctx, tmp_path):
    txt = tmp_path / "notes.pdf"
    txt.write_text("not a pdf")
    with pytest.raises(InvalidImportError, match="不是 PDF"):
        ctx.library.import_file(txt)
    with pytest.raises(InvalidImportError, match="不存在"):
        ctx.library.import_file(tmp_path / "missing.pdf")


def wait_job(client, job_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def test_sync_via_api(client, zotero):
    ctx = client.app.state.ctx
    use(ctx, zotero)
    resp = client.post("/library/sync", json={"collection_key": "ROOT"})
    assert resp.status_code == 202
    job = wait_job(client, resp.json()["id"])
    assert job["status"] == "done", job
    assert "新增 4" in job["message"] and "待解析 2" in job["message"]

    cols = client.get("/library/collections").json()
    root = next(c for c in cols if c["zotero_key"] == "ROOT")
    items = client.get("/library/items", params={"collection_id": root["id"]}).json()
    assert items["total"] == 1
    detail = client.get(f"/library/items/{items['items'][0]['id']}").json()
    assert detail["collection_ids"] == [root["id"]]
    assert client.get("/library/items/nope").status_code == 404


def test_sync_reuses_active_job(ctx):
    # ctx 夹具里 worker 没有运行，任务一直排队
    first = ctx.library.request_sync()
    assert ctx.library.request_sync("ROOT").id == first.id
    ctx.jobs.cancel(first.id)
    assert ctx.library.request_sync().id != first.id


def test_sync_job_reports_zotero_unavailable(client):
    ctx = client.app.state.ctx

    class Down(FakeConnector):
        async def list_collections(self):
            raise ZoteroUnavailableError("无法连接 Zotero 本地 API")

    use(ctx, Down([], [], {}))
    job = wait_job(client, client.post("/library/sync").json()["id"])
    assert job["status"] == "failed"
    assert job["error"].startswith("ZoteroUnavailableError: 无法连接")


def test_import_file_via_api(client, tmp_path):
    src = write_pdf(tmp_path / "paper.pdf", "content")
    resp = client.post("/library/import-file", json={"path": str(src)})
    assert resp.status_code == 200 and resp.json()["created"] is True
    assert resp.json()["item"]["documents"][0]["parse_status"] == "pending"
    bad = client.post("/library/import-file", json={"path": str(tmp_path / "nope.pdf")})
    assert bad.status_code == 400


def test_item_collections_cascade(ctx):
    with ctx.sessions.begin() as s:
        item = ItemRow(item_type="document", title="t")
        s.add(item)
        s.flush()
        col = CollectionRow(name="c")
        s.add(col)
        s.flush()
        s.add(ItemCollectionRow(item_id=item.id, collection_id=col.id))
    with ctx.sessions.begin() as s:
        s.delete(s.get(CollectionRow, col.id))
    with ctx.sessions() as s:
        assert s.query(ItemCollectionRow).count() == 0
