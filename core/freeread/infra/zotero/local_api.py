"""Zotero 7 本地 API 连接器（只读）。

前提：Zotero 7 正在运行，并在 设置 → 高级 中启用了"允许此计算机上的其他应用程序与 Zotero 通信"
（prefs: extensions.zotero.httpServer.localAPI.enabled = true）。
接口与 Zotero Web API v3 相同，库前缀为 /api/users/0/。
"""

import re
from pathlib import Path
from typing import Self
from urllib.parse import unquote, urlparse

import httpx

from freeread.infra.zotero.base import Attachment, Collection, Item

DEFAULT_BASE_URL = "http://localhost:23119/api/users/0/"
PAGE_SIZE = 100
SKIP_TYPES = frozenset({"attachment", "note", "annotation"})
YEAR_RE = re.compile(r"\b(\d{4})\b")
# 不同条目类型的"发表于"字段
VENUE_FIELDS = (
    "publicationTitle",
    "proceedingsTitle",
    "conferenceName",
    "bookTitle",
    "repository",
    "university",
    "websiteTitle",
)


class ZoteroUnavailableError(RuntimeError):
    pass


def default_data_dir() -> Path:
    return Path.home() / "Zotero"


class LocalApiConnector:
    source_id = "zotero-local"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        data_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={"Zotero-API-Version": "3"},
        )
        self.data_dir = data_dir or default_data_dir()
        # 最近一次响应头 Last-Modified-Version，即本次读取时的库版本
        self.library_version: int | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        out: list[dict] = []
        start = 0
        while True:
            q = {"format": "json", "limit": PAGE_SIZE, "start": start, **(params or {})}
            try:
                resp = await self._client.get(path, params=q)
            except httpx.ConnectError as e:
                raise ZoteroUnavailableError(
                    "无法连接 Zotero 本地 API（http://localhost:23119）。"
                    "请确认 Zotero 7 正在运行且已启用本地 API。"
                ) from e
            if resp.status_code in (403, 404) and start == 0 and "users/0" in str(resp.url):
                raise ZoteroUnavailableError(
                    f"Zotero 本地 API 返回 {resp.status_code}，可能未在设置中启用本地 API。"
                )
            resp.raise_for_status()
            if version := resp.headers.get("Last-Modified-Version"):
                self.library_version = int(version)
            page = resp.json()
            out.extend(page)
            total = resp.headers.get("Total-Results")
            start += len(page)
            if not page or len(page) < PAGE_SIZE or (total is not None and start >= int(total)):
                return out

    async def list_collections(self) -> list[Collection]:
        rows = await self._get_all("collections")
        return [
            Collection(
                key=r["key"],
                name=r["data"]["name"],
                parent_key=r["data"].get("parentCollection") or None,
            )
            for r in rows
        ]

    async def list_items(self, since_version: int | None = None) -> list[Item]:
        params = {"since": since_version} if since_version is not None else {}
        rows = await self._get_all("items", {"itemType": "-attachment", **params})
        att_rows = await self._get_all("items", {"itemType": "attachment", **params})

        attachments: dict[str, list[Attachment]] = {}
        standalone: list[Item] = []
        for r in att_rows:
            d = r["data"]
            parent = d.get("parentItem")
            if parent:
                attachments.setdefault(parent, []).append(_attachment_from_row(r))
            elif d.get("contentType") == "application/pdf":
                # 没有父条目的独立 PDF 也作为文献导入，标题取附件标题或文件名
                att = _attachment_from_row(r)
                standalone.append(
                    Item(
                        key=r["key"],
                        version=r.get("version", d.get("version", 0)),
                        item_type="attachment",
                        title=d.get("title") or att.filename or r["key"],
                        collection_keys=d.get("collections", []),
                        tags=[t["tag"] for t in d.get("tags", [])],
                        attachments=[att],
                        extra={"standalone": True},
                    )
                )

        items = []
        for r in rows:
            d = r["data"]
            if d.get("itemType") in SKIP_TYPES:
                continue
            m = YEAR_RE.search(d.get("date") or "")
            items.append(
                Item(
                    key=r["key"],
                    version=r.get("version", d.get("version", 0)),
                    item_type=d["itemType"],
                    title=d.get("title") or "",
                    creators=d.get("creators", []),
                    year=int(m.group(1)) if m else None,
                    doi=d.get("DOI") or None,
                    venue=next((d[f] for f in VENUE_FIELDS if d.get(f)), None),
                    abstract=d.get("abstractNote") or None,
                    collection_keys=d.get("collections", []),
                    tags=[t["tag"] for t in d.get("tags", [])],
                    attachments=attachments.get(r["key"], []),
                    extra={"language": d.get("language") or None},
                )
            )
        return items + standalone

    async def resolve_attachment(self, item: Item, attachment: Attachment) -> Path | None:
        candidates: list[Path] = []
        if attachment.href and attachment.href.startswith("file:"):
            candidates.append(_path_from_file_url(attachment.href))
        if attachment.path and not attachment.path.startswith("storage:"):
            candidates.append(Path(attachment.path))  # linked file
        if attachment.filename:
            candidates.append(self.data_dir / "storage" / attachment.key / attachment.filename)
        for c in candidates:
            if c.is_file():
                return c
        return None


def _attachment_from_row(r: dict) -> Attachment:
    d = r["data"]
    href = (r.get("links", {}).get("enclosure") or {}).get("href")
    return Attachment(
        key=r["key"],
        content_type=d.get("contentType") or "",
        filename=d.get("filename") or None,
        link_mode=d.get("linkMode") or None,
        path=d.get("path") or None,
        href=href,
    )


def _path_from_file_url(url: str) -> Path:
    p = unquote(urlparse(url).path)
    # file:///C:/Users/... -> /C:/Users/...
    if re.match(r"^/[A-Za-z]:", p):
        p = p[1:]
    return Path(p)
