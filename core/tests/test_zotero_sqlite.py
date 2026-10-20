"""SqliteSnapshotConnector：用最小化的 Zotero 7 表结构造一个 zotero.sqlite。"""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from freeread.infra.zotero.auto import AutoConnector
from freeread.infra.zotero.base import ZoteroUnavailableError
from freeread.infra.zotero.local_api import LocalApiConnector
from freeread.infra.zotero.sqlite_snapshot import SqliteSnapshotConnector

SCHEMA = """
CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, version INT);
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, libraryID INT, key TEXT, version INT);
CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value);
CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INT);
CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT,
  libraryID INT, key TEXT, parentCollectionID INT);
CREATE TABLE collectionItems (collectionID INT, itemID INT, orderIndex INT);
CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE itemTags (itemID INT, tagID INT, type INT);
CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT, linkMode INT,
  contentType TEXT, path TEXT);
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY);
"""


def build_db(data_dir: Path, linked_pdf: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data_dir / "zotero.sqlite")
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO libraries VALUES (?,?,?)", [(1, "user", 321), (2, "group", 5)])
    db.executemany(
        "INSERT INTO itemTypes VALUES (?,?)",
        [(1, "journalArticle"), (2, "attachment"), (3, "note"), (4, "book")],
    )
    fields = ["title", "date", "DOI", "publicationTitle", "abstractNote", "language"]
    db.executemany("INSERT INTO fields VALUES (?,?)", list(enumerate(fields, 1)))
    db.executemany(
        "INSERT INTO items VALUES (?,?,?,?,?)",
        [
            (1, 1, 1, "PAPER001", 300),  # 期刊文章
            (2, 2, 1, "ATT00001", 300),  # 导入的 PDF
            (3, 2, 1, "ATT00002", 300),  # 链接的 PDF
            (4, 3, 1, "NOTE0001", 300),  # 笔记：不是文献
            (5, 4, 1, "TRASHED1", 300),  # 回收站里
            (6, 2, 1, "STANDALO", 310),  # 独立 PDF
            (7, 4, 2, "GROUPBK1", 4),  # 群组库：不读
        ],
    )
    values = {
        (1, "title"): "A Snapshot Paper",
        (1, "date"): "2019-03-01 2019-03-01",
        (1, "DOI"): "10.1/snap",
        (1, "publicationTitle"): "Journal of Tests",
        (1, "language"): "en",
        (5, "title"): "Trashed Book",
        (6, "title"): "Scanned notes",
    }
    for i, ((item_id, field), value) in enumerate(values.items(), 1):
        db.execute("INSERT INTO itemDataValues VALUES (?,?)", (i, value))
        db.execute("INSERT INTO itemData VALUES (?,?,?)", (item_id, fields.index(field) + 1, i))
    db.executemany(
        "INSERT INTO creators VALUES (?,?,?,?)",
        [(1, "Ada", "Lovelace", 0), (2, "", "Analytical Society", 1)],
    )
    db.executemany("INSERT INTO creatorTypes VALUES (?,?)", [(1, "author"), (2, "editor")])
    db.executemany("INSERT INTO itemCreators VALUES (?,?,?,?)", [(1, 2, 2, 1), (1, 1, 1, 0)])
    db.executemany(
        "INSERT INTO collections VALUES (?,?,?,?,?)",
        [
            (1, "根", 1, "COLLROOT", None),
            (2, "子", 1, "COLLCHLD", 1),
            (3, "废弃", 1, "COLLGONE", None),
        ],
    )
    db.execute("INSERT INTO deletedCollections VALUES (3)")
    db.executemany("INSERT INTO collectionItems VALUES (?,?,?)", [(2, 1, 0), (3, 1, 1), (1, 6, 0)])
    db.executemany("INSERT INTO tags VALUES (?,?)", [(1, "ml"), (2, "snap")])
    db.executemany("INSERT INTO itemTags VALUES (?,?,0)", [(1, 1), (1, 2)])
    db.executemany(
        "INSERT INTO itemAttachments VALUES (?,?,?,?,?)",
        [
            (2, 1, 0, "application/pdf", "storage:paper.pdf"),
            (3, 1, 2, "application/pdf", str(linked_pdf)),
            (6, None, 0, "application/pdf", "storage:scan.pdf"),
        ],
    )
    db.execute("INSERT INTO deletedItems VALUES (5)")
    db.commit()
    db.close()
    for key, name in (("ATT00001", "paper.pdf"), ("STANDALO", "scan.pdf")):
        f = data_dir / "storage" / key / name
        f.parent.mkdir(parents=True)
        f.write_bytes(b"%PDF-1.4 " + key.encode())
    return data_dir / "zotero.sqlite"


@pytest.fixture
def zotero_dir(tmp_path):
    linked = tmp_path / "elsewhere" / "linked.pdf"
    linked.parent.mkdir()
    linked.write_bytes(b"%PDF-1.4 linked")
    build_db(tmp_path / "Zotero", linked)
    return tmp_path / "Zotero"


async def test_reads_snapshot_without_touching_original(zotero_dir, tmp_path):
    original = zotero_dir / "zotero.sqlite"
    before = (hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns)
    async with SqliteSnapshotConnector(zotero_dir, tmp_path / "snapshots") as c:
        cols = {x.key: x for x in await c.list_collections()}
        items = {i.key: i for i in await c.list_items()}
        assert c.library_version == 321
        paper = items["PAPER001"]
        resolved = [await c.resolve_attachment(paper, a) for a in paper.attachments]

    assert set(cols) == {"COLLROOT", "COLLCHLD"}  # 回收站里的分类不读
    assert cols["COLLCHLD"].parent_key == "COLLROOT"
    assert set(items) == {"PAPER001", "STANDALO"}  # 笔记、回收站、群组库都不读
    assert (paper.title, paper.year, paper.doi, paper.venue) == (
        "A Snapshot Paper",
        2019,
        "10.1/snap",
        "Journal of Tests",
    )
    assert paper.creators == [
        {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
        {"creatorType": "editor", "name": "Analytical Society"},
    ]
    assert paper.collection_keys == ["COLLCHLD"]
    assert sorted(paper.tags) == ["ml", "snap"]
    assert paper.extra == {"language": "en"}
    assert [(a.key, a.link_mode) for a in paper.attachments] == [
        ("ATT00001", "imported_file"),
        ("ATT00002", "linked_file"),
    ]
    assert resolved[0] == zotero_dir / "storage" / "ATT00001" / "paper.pdf"
    assert resolved[1] == tmp_path / "elsewhere" / "linked.pdf"
    standalone = items["STANDALO"]
    assert standalone.extra == {"standalone": True} and standalone.title == "Scanned notes"
    assert standalone.collection_keys == ["COLLROOT"]

    after = (hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_mtime_ns)
    assert after == before
    assert (tmp_path / "snapshots" / "zotero-snapshot.sqlite").is_file()


async def test_missing_database_is_unavailable(tmp_path):
    async with SqliteSnapshotConnector(tmp_path / "nope", tmp_path / "snap") as c:
        assert not c.available()
        with pytest.raises(ZoteroUnavailableError, match="没有找到 Zotero 数据库"):
            await c.list_collections()


def unreachable_local(data_dir: Path) -> LocalApiConnector:
    import httpx

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    return LocalApiConnector(
        base_url="http://zotero.test/api/users/0/",
        data_dir=data_dir,
        transport=httpx.MockTransport(handler),
    )


async def test_auto_falls_back_to_snapshot(zotero_dir, tmp_path):
    async with AutoConnector(
        unreachable_local(zotero_dir), SqliteSnapshotConnector(zotero_dir, tmp_path / "snap")
    ) as c:
        assert c.source_id == "zotero_local"
        assert len(await c.list_collections()) == 2
        assert c.source_id == "zotero_sqlite" and not c.incremental
        assert c.fallback_reason and "本地 API" in c.fallback_reason
        assert {i.key for i in await c.list_items()} == {"PAPER001", "STANDALO"}
        assert await c.list_keys() is None
        assert c.library_version == 321

    async with AutoConnector(
        unreachable_local(tmp_path / "none"),
        SqliteSnapshotConnector(tmp_path / "none", tmp_path / "snap"),
    ) as c:
        with pytest.raises(ZoteroUnavailableError, match="也没有在"):
            await c.list_collections()
