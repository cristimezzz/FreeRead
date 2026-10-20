"""Zotero 数据库快照连接器：Zotero 没运行时也能导入。见 docs/m2/zotero-sync.md。

绝不写用户的 zotero.sqlite：先把它（连同 -journal / -wal）复制到数据目录的 zotero-snapshots/，
再打开副本（必要时由 SQLite 在副本上回滚未完成的事务）。复制前后文件大小、修改时间不一致说明
Zotero 正在写，重试一次；仍不一致或文件被锁时报 ZoteroUnavailableError。

只读用户自己的库（libraries.type = 'user'），回收站里的条目（deletedItems）不导入，
笔记、标注不是文献。快照每次都是全量读取（本机读库很快），不做增量。
"""

import asyncio
import re
import shutil
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Self

from freeread.infra.zotero.base import (
    Attachment,
    Collection,
    Item,
    ZoteroUnavailableError,
    storage_candidates,
)

DB_NAME = "zotero.sqlite"
SNAPSHOT_NAME = "zotero-snapshot.sqlite"
SIDE_FILES = ("-journal", "-wal")
SKIP_TYPES = frozenset({"attachment", "note", "annotation"})
LINK_MODES = {0: "imported_file", 1: "imported_url", 2: "linked_file", 3: "linked_url"}
YEAR_RE = re.compile(r"\b(\d{4})\b")
VENUE_FIELDS = (
    "publicationTitle",
    "proceedingsTitle",
    "conferenceName",
    "bookTitle",
    "repository",
    "university",
    "websiteTitle",
)


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


class SqliteSnapshotConnector:
    source_id = "zotero_sqlite"
    incremental = False

    def __init__(self, data_dir: Path, snapshot_dir: Path) -> None:
        self.data_dir = data_dir
        self.snapshot_dir = snapshot_dir
        self.library_version: int | None = None
        self._db: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_NAME

    def available(self) -> bool:
        return self.db_path.is_file()

    async def aclose(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------ 快照

    def snapshot(self) -> Path:
        """复制数据库到快照目录，返回副本路径。"""
        src = self.db_path
        if not src.is_file():
            raise ZoteroUnavailableError(
                f"在 {self.data_dir} 没有找到 Zotero 数据库（{DB_NAME}）。"
                "请在 设置 › Zotero 中指定 Zotero 数据目录。"
            )
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        dest = self.snapshot_dir / SNAPSHOT_NAME
        for attempt in range(2):
            before = [_stat(Path(f"{src}{s}")) for s in ("", *SIDE_FILES)]
            try:
                for suffix in ("", *SIDE_FILES):
                    side = Path(f"{src}{suffix}")
                    target = Path(f"{dest}{suffix}")
                    if side.is_file():
                        shutil.copyfile(side, target)
                    else:
                        target.unlink(missing_ok=True)
            except OSError as e:
                raise ZoteroUnavailableError(
                    f"无法复制 Zotero 数据库（{e}）。如果 Zotero 正在运行，请改用本地 API 同步。"
                ) from e
            if before == [_stat(Path(f"{src}{s}")) for s in ("", *SIDE_FILES)]:
                return dest
            time.sleep(0.5 * (attempt + 1))
        raise ZoteroUnavailableError(
            "Zotero 数据库在复制过程中发生了变化，请稍后重试或关闭 Zotero。"
        )

    def _open(self) -> sqlite3.Connection:
        if self._db is None:
            path = self.snapshot()
            try:
                db = sqlite3.connect(path, check_same_thread=False)
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only = ON")
                db.execute("SELECT 1 FROM items LIMIT 1")
            except sqlite3.DatabaseError as e:
                raise ZoteroUnavailableError(f"无法读取 Zotero 数据库快照：{e}") from e
            self._db = db
        return self._db

    # ------------------------------------------------------------ 读取

    async def list_collections(self) -> list[Collection]:
        return await asyncio.to_thread(self._collections)

    async def list_items(self, since_version: int | None = None) -> list[Item]:
        return await asyncio.to_thread(self._items)

    async def resolve_attachment(self, item: Item, attachment: Attachment) -> Path | None:
        for c in storage_candidates(self.data_dir, attachment):
            if c.is_file():
                return c
        return None

    def _library_id(self, db: sqlite3.Connection) -> int:
        row = db.execute(
            "SELECT libraryID, version FROM libraries WHERE type = 'user' ORDER BY libraryID LIMIT 1"
        ).fetchone()
        if row is None:
            raise ZoteroUnavailableError("Zotero 数据库里没有用户文献库")
        self.library_version = row["version"]
        return row["libraryID"]

    def _collections(self) -> list[Collection]:
        db = self._open()
        lib = self._library_id(db)
        rows = db.execute(
            """
            SELECT c.collectionID, c.key, c.collectionName, p.key AS parentKey
            FROM collections c LEFT JOIN collections p ON p.collectionID = c.parentCollectionID
            WHERE c.libraryID = ?
              AND c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
            """,
            (lib,),
        ).fetchall()
        return [Collection(r["key"], r["collectionName"], r["parentKey"]) for r in rows]

    def _items(self) -> list[Item]:
        db = self._open()
        lib = self._library_id(db)
        types = _table(db, "itemTypesCombined", "itemTypes")
        fields = _table(db, "fieldsCombined", "fields")
        rows = db.execute(
            f"""
            SELECT i.itemID, i.key, i.version, t.typeName
            FROM items i JOIN {types} t ON t.itemTypeID = i.itemTypeID
            WHERE i.libraryID = ? AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            """,  # 表名来自 _table 的两个固定候选
            (lib,),
        ).fetchall()

        values: dict[int, dict[str, str]] = defaultdict(dict)
        for r in db.execute(
            f"""
            SELECT d.itemID, f.fieldName, v.value
            FROM itemData d JOIN {fields} f ON f.fieldID = d.fieldID
            JOIN itemDataValues v ON v.valueID = d.valueID
            """
        ):
            values[r["itemID"]][r["fieldName"]] = r["value"]

        creators: dict[int, list[dict]] = defaultdict(list)
        for r in db.execute(
            """
            SELECT ic.itemID, c.firstName, c.lastName, c.fieldMode, t.creatorType
            FROM itemCreators ic JOIN creators c ON c.creatorID = ic.creatorID
            JOIN creatorTypes t ON t.creatorTypeID = ic.creatorTypeID
            ORDER BY ic.itemID, ic.orderIndex
            """
        ):
            if r["fieldMode"] == 1:  # 单字段姓名（机构等）
                creators[r["itemID"]].append(
                    {"creatorType": r["creatorType"], "name": r["lastName"]}
                )
            else:
                creators[r["itemID"]].append(
                    {
                        "creatorType": r["creatorType"],
                        "firstName": r["firstName"] or "",
                        "lastName": r["lastName"] or "",
                    }
                )

        collections: dict[int, list[str]] = defaultdict(list)
        for r in db.execute(
            """
            SELECT ci.itemID, c.key FROM collectionItems ci
            JOIN collections c ON c.collectionID = ci.collectionID
            WHERE c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
            ORDER BY ci.orderIndex
            """
        ):
            collections[r["itemID"]].append(r["key"])

        tags: dict[int, list[str]] = defaultdict(list)
        for r in db.execute(
            "SELECT it.itemID, t.name FROM itemTags it JOIN tags t ON t.tagID = it.tagID"
        ):
            tags[r["itemID"]].append(r["name"])

        by_id = {r["itemID"]: r for r in rows}
        children: dict[int, list[Attachment]] = defaultdict(list)
        standalone: list[Item] = []
        for r in db.execute(
            "SELECT itemID, parentItemID, linkMode, contentType, path FROM itemAttachments"
        ):
            item = by_id.get(r["itemID"])
            if item is None:  # 在回收站里或不属于用户库
                continue
            path = r["path"] or None
            att = Attachment(
                key=item["key"],
                content_type=r["contentType"] or "",
                filename=path.removeprefix("storage:")
                if path and path.startswith("storage:")
                else (Path(path).name if path else None),
                link_mode=LINK_MODES.get(r["linkMode"]),
                path=path,
            )
            if r["parentItemID"] is not None:
                if r["parentItemID"] in by_id:
                    children[r["parentItemID"]].append(att)
            elif att.content_type == "application/pdf":
                v = values[r["itemID"]]
                standalone.append(
                    Item(
                        key=item["key"],
                        version=item["version"],
                        item_type="attachment",
                        title=v.get("title") or att.filename or item["key"],
                        collection_keys=collections[r["itemID"]],
                        tags=tags[r["itemID"]],
                        attachments=[att],
                        extra={"standalone": True},
                    )
                )

        out: list[Item] = []
        for item_id, r in by_id.items():
            if r["typeName"] in SKIP_TYPES:
                continue
            v = values[item_id]
            m = YEAR_RE.search(v.get("date") or "")
            out.append(
                Item(
                    key=r["key"],
                    version=r["version"],
                    item_type=r["typeName"],
                    title=v.get("title") or "",
                    creators=creators[item_id],
                    year=int(m.group(1)) if m else None,
                    doi=v.get("DOI") or None,
                    venue=next((v[f] for f in VENUE_FIELDS if v.get(f)), None),
                    abstract=v.get("abstractNote") or None,
                    collection_keys=collections[item_id],
                    tags=tags[item_id],
                    attachments=children[item_id],
                    extra={"language": v.get("language") or None},
                )
            )
        return out + standalone


def _table(db: sqlite3.Connection, preferred: str, fallback: str) -> str:
    """Zotero 7 有包含自定义类型 / 字段的 *Combined 视图，旧版本只有基础表。"""
    found = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')", (preferred,)
    ).fetchone()
    return preferred if found else fallback
