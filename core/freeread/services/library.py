"""文献库：Zotero 同步与手动导入 PDF。见 docs/01-architecture.md §5.1。

- Zotero 条目以 zotero_key 为外部主键 upsert；Zotero 端消失的条目标记 archived，不物理删除。
- M1 每次全量拉取（本机 47 条约 1.4 s），增量同步在 M2。
- 每个 PDF 按 sha256 去重为一个 document（doc_id = d_ + sha256 前 16 位），待解析的建 parse 任务。
- Zotero 附件原地引用；手动导入的 PDF 复制到 documents/<doc_id>/source.pdf。
"""

import asyncio
import hashlib
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import String, delete, func, select
from sqlalchemy.orm import Session

from freeread.config import DataPaths
from freeread.infra.db.base import utcnow
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import (
    AttachmentRow,
    CollectionRow,
    DocumentRow,
    ItemCollectionRow,
    ItemRow,
    ItemTagRow,
    JobRow,
    SyncStateRow,
)
from freeread.infra.jobs.queue import JobOut, JobQueue, JobStatus
from freeread.infra.jobs.worker import JobContext
from freeread.infra.zotero.base import Collection, Item, ZoteroConnector

ZOTERO_LOCAL_SOURCE = "zotero_local"
PDF_MAGIC = b"%PDF-"
HASH_CHUNK = 1 << 20

ConnectorFactory = Callable[[], ZoteroConnector]
Progress = Callable[[float, str | None], Awaitable[None]]


class InvalidImportError(ValueError):
    """导入的文件不存在或不是 PDF。"""


ItemSort = Literal["added", "title", "year"]


class CollectionOut(BaseModel):
    """扁平列表，前端按 parent_id 组装分类树。"""

    id: str
    zotero_key: str | None
    name: str
    parent_id: str | None
    item_count: int  # 直接属于该分类的有效条目数（不含子分类）


class DocRef(BaseModel):
    attachment_id: str
    doc_id: str | None
    filename: str
    parse_status: str | None  # pending | parsing | ready | failed


class ItemOut(BaseModel):
    id: str
    zotero_key: str | None
    item_type: str
    title: str
    authors: list[dict[str, Any]]
    year: int | None
    venue: str | None
    doi: str | None
    status: str
    created_at: str
    documents: list[DocRef]


class ItemDetail(ItemOut):
    abstract: str | None = None
    tags: list[str] = []
    collection_ids: list[str] = []
    extra: dict[str, Any] = {}


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    archived: int = 0
    collections: int = 0
    missing_files: int = 0
    parse_jobs: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"新增 {self.added}，更新 {self.updated}，归档 {self.archived}，"
            f"缺失文件 {self.missing_files}，待解析 {len(self.parse_jobs)}"
        )


@dataclass
class _ResolvedItem:
    item: Item
    pdfs: list[tuple[str, Path]]  # (attachment key, 本地路径)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def doc_id_for(sha256: str) -> str:
    return f"d_{sha256[:16]}"


def authors_from_creators(creators: list[dict]) -> list[dict]:
    out = []
    for c in creators:
        if c.get("name"):
            out.append({"name": c["name"], "type": c.get("creatorType", "author")})
        else:
            out.append(
                {
                    "first": c.get("firstName", ""),
                    "last": c.get("lastName", ""),
                    "type": c.get("creatorType", "author"),
                }
            )
    return out


class LibraryService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        jobs: JobQueue,
        connector_factory: ConnectorFactory,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._jobs = jobs
        self.connector_factory = connector_factory

    # ------------------------------------------------------------ 任务

    def request_sync(self, collection_key: str | None = None) -> JobOut:
        """建 sync 任务；已有排队中 / 运行中的 sync 时直接返回它。"""
        active = self._jobs.list([JobStatus.QUEUED, JobStatus.RUNNING], kind="sync", limit=1)
        if active:
            return active[0]
        return self._jobs.enqueue("sync", {"collection_key": collection_key})

    async def run_sync_job(self, ctx: JobContext) -> None:
        result = await self.sync_zotero(ctx.job.payload.get("collection_key"), ctx.report)
        await ctx.report(1.0, result.summary())

    # ------------------------------------------------------------ Zotero 同步

    async def sync_zotero(
        self, collection_key: str | None = None, progress: Progress | None = None
    ) -> SyncResult:
        """全量同步元数据；只为 collection_key（含子分类）下的条目建解析任务，None 表示全部。"""

        async def report(p: float, msg: str) -> None:
            if progress:
                await progress(p, msg)

        connector = self.connector_factory()
        try:
            await report(0.05, "读取 Zotero 分类")
            collections = await connector.list_collections()
            await report(0.2, "读取 Zotero 条目")
            items = await connector.list_items()
            await report(0.5, "解析附件路径")
            resolved = []
            missing = 0
            for item in items:
                pdfs = []
                for att in item.attachments:
                    if att.content_type != "application/pdf":
                        continue
                    path = await connector.resolve_attachment(item, att)
                    if path is None:
                        missing += 1
                    else:
                        pdfs.append((att.key, path))
                resolved.append(_ResolvedItem(item, pdfs))
            version = getattr(connector, "library_version", None)
        finally:
            aclose = getattr(connector, "aclose", None)
            if aclose:
                await aclose()

        await report(0.6, "写入文献库")
        result = await asyncio.to_thread(
            self._apply_sync, collections, resolved, collection_key, version
        )
        result.missing_files = missing
        return result

    def _apply_sync(
        self,
        collections: list[Collection],
        resolved: list[_ResolvedItem],
        collection_key: str | None,
        library_version: int | None,
    ) -> SyncResult:
        result = SyncResult(collections=len(collections))
        to_parse: set[str] = set()
        hashes = self._hash_attachments(resolved)
        with self._sessions.begin() as s:
            col_ids = self._upsert_collections(s, collections)
            if collection_key is not None and collection_key not in col_ids:
                raise ValueError(f"Zotero 中没有分类 {collection_key}")
            scope = _descendants(collections, collection_key) if collection_key else None

            seen: set[str] = set()
            for r in resolved:
                item = r.item
                seen.add(item.key)
                row = s.scalar(select(ItemRow).where(ItemRow.zotero_key == item.key))
                if row is None:
                    row = ItemRow(zotero_key=item.key, zotero_library_id="local")
                    s.add(row)
                    result.added += 1
                elif row.zotero_version != item.version or row.status != "active":
                    result.updated += 1
                _fill_item(row, item)
                s.flush()

                s.execute(delete(ItemCollectionRow).where(ItemCollectionRow.item_id == row.id))
                for key in dict.fromkeys(item.collection_keys):
                    if key in col_ids:
                        s.add(ItemCollectionRow(item_id=row.id, collection_id=col_ids[key]))
                s.execute(delete(ItemTagRow).where(ItemTagRow.item_id == row.id))
                for tag in dict.fromkeys(item.tags):
                    s.add(ItemTagRow(item_id=row.id, tag=tag))

                in_scope = scope is None or bool(scope & set(item.collection_keys))
                for att_key, path in r.pdfs:
                    doc_id = self._upsert_attachment(s, row.id, att_key, path, hashes[att_key])
                    if in_scope:
                        to_parse.add(doc_id)

            stale = s.scalars(
                select(ItemRow).where(
                    ItemRow.zotero_key.is_not(None),
                    ItemRow.zotero_key.not_in(seen),
                    ItemRow.status == "active",
                )
            ).all()
            for row in stale:
                row.status = "archived"
            result.archived = len(stale)

            s.merge(
                SyncStateRow(
                    source=ZOTERO_LOCAL_SOURCE,
                    last_version=library_version,
                    last_synced_at=utcnow(),
                )
            )
        result.parse_jobs = self._enqueue_parse(sorted(to_parse))
        return result

    def _upsert_collections(self, s: Session, collections: list[Collection]) -> dict[str, str]:
        existing = {
            r.zotero_key: r
            for r in s.scalars(select(CollectionRow).where(CollectionRow.zotero_key.is_not(None)))
        }
        ids: dict[str, str] = {}
        for c in collections:
            row = existing.pop(c.key, None)
            if row is None:
                row = CollectionRow(zotero_key=c.key, name=c.name)
                s.add(row)
            row.name = c.name
            s.flush()
            ids[c.key] = row.id
        for c in collections:
            s.get(CollectionRow, ids[c.key]).parent_id = ids.get(c.parent_key or "")
        for row in existing.values():  # Zotero 中已删除的分类
            s.delete(row)
        s.flush()
        return ids

    def _hash_attachments(self, resolved: list[_ResolvedItem]) -> dict[str, str]:
        """在写事务之外计算 sha256。路径没变就沿用上次的哈希，避免每次同步都重读所有 PDF。"""
        with self._sessions() as s:
            known = {
                r.zotero_key: (r.path, r.sha256)
                for r in s.scalars(
                    select(AttachmentRow).where(AttachmentRow.zotero_key.is_not(None))
                )
            }
        hashes = {}
        for r in resolved:
            for att_key, path in r.pdfs:
                old_path, old_sha = known.get(att_key, (None, None))
                hashes[att_key] = (
                    old_sha if old_sha and old_path == str(path) else sha256_file(path)
                )
        return hashes

    def _upsert_attachment(
        self, s: Session, item_id: str, att_key: str, path: Path, sha256: str
    ) -> str:
        row = s.scalar(select(AttachmentRow).where(AttachmentRow.zotero_key == att_key))
        if row is None:
            row = AttachmentRow(item_id=item_id, zotero_key=att_key, path=str(path))
            s.add(row)
        row.sha256 = sha256
        row.item_id = item_id
        row.path = str(path)
        row.content_type = "application/pdf"
        row.doc_id = self._ensure_document(s, row.sha256)
        s.flush()
        return row.doc_id

    @staticmethod
    def _ensure_document(s: Session, sha256: str) -> str:
        doc_id = doc_id_for(sha256)
        if s.get(DocumentRow, doc_id) is None:
            s.add(DocumentRow(doc_id=doc_id, pdf_sha256=sha256))
            s.flush()
        return doc_id

    def _enqueue_parse(self, doc_ids: list[str]) -> list[str]:
        """为待解析（pending / failed）且没有排队中解析任务的文档建 parse 任务。"""
        if not doc_ids:
            return []
        with self._sessions() as s:
            needs = set(
                s.scalars(
                    select(DocumentRow.doc_id).where(
                        DocumentRow.doc_id.in_(doc_ids),
                        DocumentRow.parse_status.in_(["pending", "failed"]),
                    )
                )
            )
            active = set(
                s.scalars(
                    select(JobRow.payload["doc_id"].as_string()).where(
                        JobRow.kind == "parse",
                        JobRow.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    )
                )
            )
        return [
            self._jobs.enqueue("parse", {"doc_id": d}).id for d in doc_ids if d in needs - active
        ]

    # ------------------------------------------------------------ 手动导入

    def import_file(self, src: Path) -> tuple[str, bool]:
        """导入本地 PDF，返回 (item_id, 是否新建)。同一 PDF 已手动导入过时直接返回原条目。"""
        if not src.is_file():
            raise InvalidImportError(f"文件不存在：{src}")
        with src.open("rb") as f:
            if f.read(len(PDF_MAGIC)) != PDF_MAGIC:
                raise InvalidImportError(f"不是 PDF 文件：{src.name}")
        sha = sha256_file(src)
        doc_id = doc_id_for(sha)
        dest = self._paths.document_dir(doc_id) / "source.pdf"

        with self._sessions.begin() as s:
            existing = s.scalar(
                select(AttachmentRow)
                .join(ItemRow, AttachmentRow.item_id == ItemRow.id)
                .where(AttachmentRow.doc_id == doc_id, ItemRow.zotero_key.is_(None))
            )
            if existing is not None:
                return existing.item_id, False

            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".tmp")
                shutil.copyfile(src, tmp)
                tmp.replace(dest)
            self._ensure_document(s, sha)
            pdf_title = _pdf_title(dest)
            item = ItemRow(
                item_type="document",
                title=pdf_title or src.stem,
                # title_source = filename 的标题会在解析后用 IR 识别出的标题替换
                extra={
                    "imported_from": str(src),
                    "title_source": "pdf_meta" if pdf_title else "filename",
                },
            )
            s.add(item)
            s.flush()
            s.add(AttachmentRow(item_id=item.id, path=str(dest), sha256=sha, doc_id=doc_id))
            item_id = item.id
        self._enqueue_parse([doc_id])
        return item_id, True

    # ------------------------------------------------------------ 查询

    def list_collections(self) -> list[CollectionOut]:
        with self._sessions() as s:
            counts = dict(
                s.execute(
                    select(ItemCollectionRow.collection_id, func.count())
                    .join(ItemRow, ItemRow.id == ItemCollectionRow.item_id)
                    .where(ItemRow.status == "active")
                    .group_by(ItemCollectionRow.collection_id)
                ).all()
            )
            rows = s.scalars(select(CollectionRow).order_by(CollectionRow.name)).all()
            return [
                CollectionOut(
                    id=r.id,
                    zotero_key=r.zotero_key,
                    name=r.name,
                    parent_id=r.parent_id,
                    item_count=counts.get(r.id, 0),
                )
                for r in rows
            ]

    def list_items(
        self,
        collection_id: str | None = None,
        q: str | None = None,
        status: str = "active",
        sort: ItemSort = "added",
        offset: int = 0,
        limit: int = 50,
    ) -> ItemPage:
        query = select(ItemRow).where(ItemRow.status == status)
        if collection_id:
            query = query.join(ItemCollectionRow, ItemCollectionRow.item_id == ItemRow.id).where(
                ItemCollectionRow.collection_id == collection_id
            )
        if q:
            # M1 用 LIKE；FTS5 在 M2 加入
            pattern = f"%{_escape_like(q)}%"
            query = query.where(
                ItemRow.title.ilike(pattern, escape="\\")
                | func.cast(ItemRow.authors, String).ilike(pattern, escape="\\")
            )
        order = {
            "added": (ItemRow.created_at.desc(), ItemRow.id.desc()),
            "title": (ItemRow.title, ItemRow.id),
            "year": (ItemRow.year.desc().nulls_last(), ItemRow.title),
        }[sort]
        with self._sessions() as s:
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(query.order_by(*order).offset(offset).limit(limit)).all()
            docs = self._doc_refs(s, [r.id for r in rows])
            items = [_item_out(ItemOut, r, docs.get(r.id, [])) for r in rows]
        return ItemPage(items=items, total=total)

    def get_item(self, item_id: str) -> ItemDetail | None:
        with self._sessions() as s:
            row = s.get(ItemRow, item_id)
            if row is None:
                return None
            tags = s.scalars(select(ItemTagRow.tag).where(ItemTagRow.item_id == item_id)).all()
            cols = s.scalars(
                select(ItemCollectionRow.collection_id).where(ItemCollectionRow.item_id == item_id)
            ).all()
            out = _item_out(ItemDetail, row, self._doc_refs(s, [item_id]).get(item_id, []))
            out.abstract = row.abstract
            out.tags = sorted(tags)
            out.collection_ids = list(cols)
            out.extra = row.extra
            return out

    @staticmethod
    def _doc_refs(s: Session, item_ids: list[str]) -> dict[str, list[DocRef]]:
        if not item_ids:
            return {}
        rows = s.execute(
            select(AttachmentRow, DocumentRow.parse_status)
            .outerjoin(DocumentRow, DocumentRow.doc_id == AttachmentRow.doc_id)
            .where(AttachmentRow.item_id.in_(item_ids))
            .order_by(AttachmentRow.id)
        ).all()
        out: dict[str, list[DocRef]] = {}
        for att, parse_status in rows:
            out.setdefault(att.item_id, []).append(
                DocRef(
                    attachment_id=att.id,
                    doc_id=att.doc_id,
                    filename=Path(att.path).name,
                    parse_status=parse_status,
                )
            )
        return out


def _item_out(cls: type[ItemOut], row: ItemRow, docs: list[DocRef]) -> ItemOut:
    return cls(
        id=row.id,
        zotero_key=row.zotero_key,
        item_type=row.item_type,
        title=row.title,
        authors=row.authors,
        year=row.year,
        venue=row.venue,
        doi=row.doi,
        status=row.status,
        created_at=row.created_at,
        documents=docs,
    )


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fill_item(row: ItemRow, item: Item) -> None:
    row.zotero_version = item.version
    row.item_type = item.item_type
    row.title = item.title
    row.authors = authors_from_creators(item.creators)
    row.year = item.year
    row.doi = item.doi
    row.venue = item.venue
    row.abstract = item.abstract
    row.extra = {k: v for k, v in item.extra.items() if v is not None}
    row.status = "active"


def _descendants(collections: list[Collection], root: str) -> set[str]:
    children: dict[str, list[str]] = {}
    for c in collections:
        if c.parent_key:
            children.setdefault(c.parent_key, []).append(c.key)
    out, stack = set(), [root]
    while stack:
        key = stack.pop()
        if key not in out:
            out.add(key)
            stack.extend(children.get(key, []))
    return out


def _pdf_title(path: Path) -> str | None:
    try:
        import pymupdf

        with pymupdf.open(path) as doc:
            title = (doc.metadata or {}).get("title", "").strip()
    except (RuntimeError, ValueError):  # pymupdf.FileDataError 是 RuntimeError 的子类
        return None
    # 很多 PDF 的元数据标题是 "Microsoft Word - xxx.docx" 之类，太短或像文件名的不用
    if len(title) < 8 or title.lower().endswith((".doc", ".docx", ".tex", ".dvi", ".pdf")):
        return None
    return title
