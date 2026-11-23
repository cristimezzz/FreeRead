"""按设置选择 Zotero 数据源。auto：优先用本地 API，不可用时（Zotero 没运行、没开本地 API、
超时、出错）改读数据库快照。

- 第一次读取前用短超时探测本地 API（select），连不上时几秒内就改用快照，不用等完整超时。
- 读取途中本地 API 断开（比如用户退出了 Zotero），调用方可以 fall_back() 切到快照后从头重读，
  见 LibraryService.sync_zotero。
"""

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
        self._selected = False
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

    async def select(self) -> None:
        """确定数据源：本地 API 探测通过就用它，否则改用快照（快照也没有时报错）。"""
        if self._selected:
            return
        self._selected = True
        try:
            await self._local.probe()
        except ZoteroUnavailableError as e:
            if not self.fall_back(str(e)):
                raise ZoteroUnavailableError(
                    f"{e} 也没有在 {self._snapshot.data_dir} 找到 Zotero 数据库，"
                    "可以在 设置 › Zotero 中指定数据目录。"
                ) from e

    def fall_back(self, reason: str) -> bool:
        """当前在用本地 API 且有数据库可读时切到快照，返回 True；否则 False。"""
        self._selected = True
        if self._active is not self._local or not self._snapshot.available():
            return False
        self.fallback_reason = reason
        self._active = self._snapshot
        return True

    async def list_collections(self) -> list[Collection]:
        await self.select()
        return await self._active.list_collections()

    async def list_items(self, since_version: int | None = None) -> list[Item]:
        await self.select()
        return await self._active.list_items(since_version)

    async def list_keys(self) -> set[str] | None:
        await self.select()
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
