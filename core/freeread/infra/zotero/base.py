"""Zotero 接入接口。见 docs/01-architecture.md §5.1、docs/m2/zotero-sync.md。

实现：LocalApiConnector（Zotero 7 本地 API）、SqliteSnapshotConnector（只读快照，绝不写原库）、
AutoConnector（先本地 API，Zotero 没运行时用快照）；以后有 WebApiConnector（Zotero Web API）。

增量同步是可选能力：connector.incremental 为真时，list_items(since_version) 只返回该版本之后
变化的条目（条目下的附件列表是完整的），list_keys() 返回库里现存的全部条目 key（含附件、
不含回收站），用来发现删除；不支持时返回 None，由调用方退回全量同步。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Collection:
    key: str
    name: str
    parent_key: str | None = None


@dataclass
class Attachment:
    key: str
    content_type: str
    filename: str | None = None
    link_mode: str | None = None  # imported_file | imported_url | linked_file | linked_url
    path: str | None = None  # "storage:<filename>" 或链接文件的绝对路径
    href: str | None = None  # 本地 API 的 links.enclosure.href（file:/// URL）


@dataclass
class Item:
    key: str
    version: int
    item_type: str
    title: str
    creators: list[dict] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    venue: str | None = None
    abstract: str | None = None
    collection_keys: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class ZoteroUnavailableError(RuntimeError):
    """Zotero 数据源不可用（本地 API 连不上、找不到数据目录、数据库被占用等）。"""


def storage_candidates(data_dir: Path, attachment: Attachment) -> list[Path]:
    """附件在本机可能的位置：链接文件的绝对路径、数据目录 storage/<key>/<文件名>。"""
    out: list[Path] = []
    if attachment.path and not attachment.path.startswith(("storage:", "attachments:")):
        out.append(Path(attachment.path))  # linked file
    filename = attachment.filename
    if not filename and attachment.path and attachment.path.startswith("storage:"):
        filename = attachment.path.removeprefix("storage:")
    if filename:
        out.append(data_dir / "storage" / attachment.key / filename)
    return out


class ZoteroConnector(Protocol):
    source_id: str

    async def list_collections(self) -> list[Collection]: ...

    async def list_items(self, since_version: int | None = None) -> list[Item]: ...

    async def resolve_attachment(self, item: Item, attachment: Attachment) -> Path | None: ...
