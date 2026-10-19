"""通过 docling-serve（自部署或第三方实例）的 v1 API 解析。见 ADR-0008。

提交 POST /v1/convert/file/async（multipart files + 选项表单字段）→ 轮询 GET /v1/status/poll/{task_id}
→ 取结果 GET /v1/result/{task_id}（默认只能取一次），DoclingDocument 在 document.json_content。
选项与 scripts/engines/run_docling.py 对齐：OCR + 表格结构 + 公式 LaTeX 增强，不导出图片。
产物与本机引擎相同：raw/docling.json + engine.json，由 DoclingNormalizer 规范化。
"""

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

import httpx

from freeread.infra.parsers.base import ParserCaps, ProgressCb, RawLayout
from freeread.infra.parsers.remote_common import RemoteClient, RemoteParseError

POLL_TIMEOUT = 3600.0
OPTIONS = {
    "to_formats": "json",
    "do_ocr": "true",
    "do_table_structure": "true",
    "do_formula_enrichment": "true",
    "image_export_mode": "placeholder",
}


class DoclingServeParser:
    name = "docling"
    version = "api"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key = api_key or None
        self._transport = transport
        self._poll = poll_interval

    def capabilities(self) -> ParserCaps:
        return ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False)

    def client(self) -> RemoteClient:
        auth = {"X-Api-Key": self._key} if self._key else {}
        return RemoteClient("Docling", self._base_url, auth, self._key, transport=self._transport)

    async def server_version(self, cli: RemoteClient) -> str | None:
        """GET /version 返回各 docling 包版本；服务可关闭此接口（403），拿不到就算了。"""
        try:
            data = await cli.json("GET", "/version")
        except RemoteParseError:
            return None
        for key in ("docling-serve", "docling_serve", "docling"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return None

    async def check(self) -> str | None:
        """测试连接：服务可达、密钥有效。返回服务端版本；失败抛 RemoteParseError。"""
        async with self.client() as cli:
            await cli.request("GET", "/health")
            try:
                # 查询一个不存在的任务：密钥错误时 401/403，否则 404 之类，均说明鉴权已通过
                await cli.request("GET", "/v1/status/poll/freeread-connection-test")
            except RemoteParseError as exc:
                if exc.code == "unauthorized":
                    raise
            return await self.server_version(cli)

    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout:
        out_dir.mkdir(parents=True, exist_ok=True)
        async with self.client() as cli:
            progress(0.0, "上传 PDF 到 Docling 服务")
            task = await cli.json(
                "POST",
                "/v1/convert/file/async",
                files={"files": (pdf.name, pdf.read_bytes(), "application/pdf")},
                data=OPTIONS,
            )
            task = await self._wait(cli, task, progress)
            if task.get("task_status") != "success":
                raise RemoteParseError("job_failed", "Docling：解析失败")
            progress(0.95, "下载解析结果")
            result = await cli.json("GET", f"/v1/result/{task['task_id']}")
            version = await self.server_version(cli) or "serve"

        if result.get("status") not in ("success", "partial_success"):
            errors = "; ".join(
                str(e.get("error_message", e)) if isinstance(e, dict) else str(e)
                for e in result.get("errors") or []
            )
            raise RemoteParseError(
                "job_failed", f"Docling：解析失败（{errors or result.get('status')}）"
            )
        doc = (result.get("document") or {}).get("json_content")
        if not isinstance(doc, dict) or not doc:
            raise RemoteParseError("bad_output", "Docling：结果里没有 DoclingDocument JSON")

        (out_dir / "docling.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        (out_dir / "engine.json").write_text(
            json.dumps(
                {
                    "engine": "docling",
                    "engine_version": version,
                    "transport": "api",
                    "formula_enrichment": True,
                }
            ),
            encoding="utf-8",
        )
        progress(1.0, "Docling：完成")
        return RawLayout("docling", version, out_dir, None)

    async def _wait(
        self, cli: RemoteClient, task: dict[str, Any], progress: ProgressCb
    ) -> dict[str, Any]:
        started = time.monotonic()
        while task.get("task_status") not in ("success", "failure"):
            elapsed = time.monotonic() - started
            if elapsed > POLL_TIMEOUT:
                raise RemoteParseError("timeout", "Docling：任务一小时内未完成")
            if task.get("task_status") == "started":
                progress(0.1 + 0.8 * (1 - math.exp(-elapsed / 90)), "Docling：解析中")
            else:
                progress(0.05, "Docling：排队中")
            await asyncio.sleep(self._poll)
            task = await cli.json("GET", f"/v1/status/poll/{task['task_id']}")
        return task
