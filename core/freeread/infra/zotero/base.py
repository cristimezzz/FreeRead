"""Zotero 接入接口。见 docs/01-architecture.md §5.1。

实现：LocalApiConnector（Zotero 7 本地 API）、SqliteSnapshotConnector（只读快照，绝不写原库）、
WebApiConnector（Zotero Web API）。
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
    abstract: str | None = None
    collection_keys: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class ZoteroConnector(Protocol):
    source_id: str

    async def list_collections(self) -> list[Collection]: ...

    async def list_items(self, since_version: int | None = None) -> list[Item]: ...

    async def resolve_attachment(self, item: Item, attachment: Attachment) -> Path | None: ...
