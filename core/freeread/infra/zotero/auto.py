"""按设置选择 Zotero 数据源。auto：先连本地 API，连不上（Zotero 没运行或没开本地 API）时
改用数据库快照。第一次调用 list_collections 时决定，之后都用同一个。"""

from pathlib import Path
from typing import Self

from freeread.infra.zotero.base import Attachment, Collection, Item
from freeread.infra.zotero.local_api import LocalApiConnector, ZoteroUnavailableError
from freeread.infra.zotero.sqlite_snapshot import SqliteSnapshotConnector


class AutoConnector:
    def __init__(self, local: LocalApiConnector, snapshot: SqliteSnapshotConnector) -> None:
        self._local = local
        self._snapshot = snapshot
        self._active: LocalApiConnector | SqliteSnapshotConnector = local
        self.fallback_reason: str | None = None

    @property
    def source_id(self) -> str:
        return self._active.source_id

    @property
    def incremental(self) -> bool:
        return self._active.incremental

    @property
    def library_version(self) -> int | None:
        return self._active.library_version

    async def list_collections(self) -> list[Collection]:
        if self._active is self._local:
            try:
                return await self._local.list_collections()
            except ZoteroUnavailableError as e:
                if not self._snapshot.available():
                    raise ZoteroUnavailableError(
                        f"{e} 也没有在 {self._snapshot.data_dir} 找到 Zotero 数据库，"
                        "可以在 设置 › Zotero 中指定数据目录。"
                    ) from e
                self.fallback_reason = str(e)
                self._active = self._snapshot
        return await self._active.list_collections()

    async def list_items(self, since_version: int | None = None) -> list[Item]:
        return await self._active.list_items(since_version)

    async def list_keys(self) -> set[str] | None:
        fn = getattr(self._active, "list_keys", None)
        return await fn() if fn else None

    async def resolve_attachment(self, item: Item, attachment: Attachment) -> Path | None:
        return await self._active.resolve_attachment(item, attachment)

    async def aclose(self) -> None:
        await self._local.aclose()
        await self._snapshot.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()
