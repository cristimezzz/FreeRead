"""通用文件下载：流式写 .part、断点续传、sha256 校验后改名。

不只用于嵌入模型；打包版 MinerU 的独立环境（M2 跟进项）也可以复用。
"""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CHUNK = 1 << 20
Progress = Callable[[int, int], Awaitable[None]]  # (已下载字节, 总字节)


@dataclass(frozen=True)
class DownloadItem:
    url: str
    dest: Path
    sha256: str
    size: int


class DownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def is_complete(item: DownloadItem) -> bool:
    return item.dest.is_file() and item.dest.stat().st_size == item.size


async def download_all(
    items: Sequence[DownloadItem],
    client: httpx.AsyncClient,
    progress: Progress | None = None,
    *,
    report_every: int = 4 * CHUNK,
) -> None:
    total = sum(i.size for i in items)
    done = sum(i.size for i in items if is_complete(i))
    for item in items:
        if is_complete(item):
            continue
        done = await _download_one(item, client, progress, done, total, report_every)
    if progress:
        await progress(total, total)


async def _download_one(
    item: DownloadItem,
    client: httpx.AsyncClient,
    progress: Progress | None,
    done: int,
    total: int,
    report_every: int,
) -> int:
    item.dest.parent.mkdir(parents=True, exist_ok=True)
    part = item.dest.with_name(item.dest.name + ".part")
    offset = part.stat().st_size if part.is_file() else 0
    if offset > item.size:
        part.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    async with client.stream("GET", item.url, headers=headers, follow_redirects=True) as resp:
        if resp.status_code == 416:  # 已经下完（.part 与文件等长）
            pass
        elif resp.status_code == 200 and offset:
            offset = 0  # 服务器不支持 Range，从头下
        elif resp.status_code not in (200, 206):
            raise DownloadError(f"下载失败：HTTP {resp.status_code} {item.url}")
        if resp.status_code != 416:
            mode = "ab" if offset else "wb"
            last = 0
            with part.open(mode) as f:
                async for block in resp.aiter_bytes(CHUNK):
                    f.write(block)
                    offset += len(block)
                    if progress and offset - last >= report_every:
                        last = offset
                        await progress(done + offset, total)
    actual = await asyncio.to_thread(sha256_file, part)
    if actual != item.sha256:
        part.unlink(missing_ok=True)
        raise DownloadError(f"校验失败：{item.dest.name} 的 sha256 为 {actual}，应为 {item.sha256}")
    part.replace(item.dest)
    log.info("downloaded %s (%d bytes)", item.dest, item.size)
    return done + item.size
