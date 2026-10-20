"""通过 MinerU v1 REST API 解析：本机 / 局域网的 `mineru-api` 与云端 https://mineru.net/api 同一协议。

流程（与 mineru/parser/api_client.py 一致，但只依赖 httpx，不 import mineru）：
上传 POST /v1/uploads → PUT upload_url → POST /v1/uploads/{id}/complete
提交 POST /v1/parse/jobs（output_formats=["middle_json"]）→ 轮询 GET /v1/parse/jobs/{id}
下载 GET /v1/files/{file_id}/content。
产物与本机引擎相同：raw/middle.json（docvortex.middle 2.0）+ engine.json，由 MinerUNormalizer 规范化；
服务端返回 3.x 的 pdf_info 格式时先经 mineru_legacy 升级。
图表图片不下载：解析任务按 bbox 从 PDF 重新截取。见 ADR-0008。
"""

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import httpx

from freeread.infra.parsers.base import ParserCaps, ProgressCb, RawLayout
from freeread.infra.parsers.mineru_legacy import (
    is_legacy_middle,
    legacy_version,
    upgrade_legacy_middle,
)
from freeread.infra.parsers.remote_common import RemoteClient, RemoteParseError, is_loopback_url

TERMINAL = {"completed", "partial", "failed", "canceled"}
POLL_TIMEOUT = 3600.0


def _strip_images(o: Any) -> None:
    """丢弃内联图片（base64），只留结构；同 scripts/engines/run_mineru._strip_images(img_dir=None)。"""
    if isinstance(o, dict):
        if isinstance(o.get("image_base64"), str):
            o["image_base64"] = None
        for v in o.values():
            _strip_images(v)
    elif isinstance(o, list):
        for v in o:
            _strip_images(v)


def _same_origin(a: str, b: str) -> bool:
    pa, pb = httpx.URL(a), httpx.URL(b)
    return (pa.scheme, pa.host, pa.port) == (pb.scheme, pb.host, pb.port)


class MinerUApiParser:
    name = "mineru"
    version = "api"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        tier: str = "basic",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key = api_key or None
        self._tier = tier
        self._transport = transport
        self._poll = poll_interval

    def capabilities(self) -> ParserCaps:
        return ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False)

    def client(self) -> RemoteClient:
        auth = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        return RemoteClient("MinerU", self._base_url, auth, self._key, transport=self._transport)

    async def health(self, cli: RemoteClient) -> dict[str, Any]:
        return await cli.json("GET", "/v1/health")

    async def check(self) -> str | None:
        """测试连接：服务可达、密钥有效。返回服务端版本；失败抛 RemoteParseError。"""
        async with self.client() as cli:
            health = await self.health(cli)
            if self._key:
                # /v1/health 不校验密钥；/v1/usage 按调用方身份返回用量，密钥错误时 401
                try:
                    await cli.request("GET", "/v1/usage")
                except RemoteParseError as exc:
                    if exc.code == "unauthorized":
                        raise
        return health.get("version")

    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout:
        out_dir.mkdir(parents=True, exist_ok=True)
        async with self.client() as cli:
            progress(0.0, "连接 MinerU 服务")
            health = await self.health(cli)
            sources = (health.get("features") or {}).get("sources") or []
            if is_loopback_url(self._base_url) and "local" in sources:
                # 同机服务（--allow-local-source）直接读文件，省去上传
                source: dict[str, Any] = {"type": "local", "path": str(pdf.resolve())}
            else:
                progress(0.02, "上传 PDF")
                source = {"type": "file_id", "file_id": await self._upload(cli, pdf)}

            body = {
                "files": [{"source": source}],
                "output_formats": ["middle_json"],
                "tier": self._tier,
            }
            job = await cli.json("POST", "/v1/parse/jobs", json=body)
            try:
                job = await self._wait(cli, job, progress)
            except asyncio.CancelledError:
                await self._cancel(cli, job.get("job_id"))
                raise

            file = self._result_file(job)
            ref = (file.get("output_files") or {}).get("middle_json") or {}
            if not ref.get("file_id"):
                raise RemoteParseError("bad_output", "MinerU：任务结果里没有 middle_json")
            progress(0.95, "下载解析结果")
            raw = await cli.request("GET", f"/v1/files/{ref['file_id']}/content")
            try:
                middle = json.loads(raw.content)
            except ValueError:
                raise RemoteParseError("bad_output", "MinerU：middle_json 不是合法 JSON") from None
            legacy = None
            if is_legacy_middle(middle):
                # mineru.net 仍可能按 3.x 协议返回（pdf_info，坐标为 pt）：升级成 4.x 形状
                legacy = legacy_version(middle) or "3.x"
                try:
                    middle = upgrade_legacy_middle(middle)
                except ValueError as exc:
                    raise RemoteParseError(
                        "bad_output", f"MinerU：无法读取 3.x 格式的 middle_json（{exc}）"
                    ) from None
            if not isinstance(middle, dict) or "docvortex_layout" not in (
                middle.get("extensions") or {}
            ):
                raise RemoteParseError(
                    "bad_output", "MinerU：无法识别服务端返回的 middle_json 格式"
                )
            _strip_images(middle)

        engine_version = (
            legacy
            or (file.get("parse") or {}).get("parser_version")
            or health.get("version")
            or "api"
        )
        (out_dir / "middle.json").write_text(
            json.dumps(middle, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "engine.json").write_text(
            json.dumps(
                {
                    "engine": "mineru",
                    "engine_version": engine_version,
                    "transport": "api",
                    "tier": self._tier,
                }
            ),
            encoding="utf-8",
        )
        progress(1.0, "MinerU：完成")
        return RawLayout("mineru", engine_version, out_dir, None)

    async def _upload(self, cli: RemoteClient, pdf: Path) -> str:
        data = pdf.read_bytes()
        created = await cli.json(
            "POST",
            "/v1/uploads",
            json={
                "filename": pdf.name,
                "bytes": len(data),
                "mime_type": "application/pdf",
                "purpose": "parse",
                "sha256sum": hashlib.sha256(data).hexdigest(),
            },
        )
        if created.get("status") == "completed":  # 服务端已有同哈希的文件
            return created["file"]["id"]
        url = cli.url(created["upload_url"])
        headers = created.get("upload_headers") or {}
        # 预签名地址（如对象存储）不能带 API Key
        await cli.request(
            "PUT", url, auth=_same_origin(url, cli.base_url), headers=headers, content=data
        )
        done = await cli.json("POST", f"/v1/uploads/{created['id']}/complete")
        return done["file"]["id"]

    async def _wait(
        self, cli: RemoteClient, job: dict[str, Any], progress: ProgressCb
    ) -> dict[str, Any]:
        started = time.monotonic()
        while job.get("status") not in TERMINAL:
            elapsed = time.monotonic() - started
            if elapsed > POLL_TIMEOUT:
                raise RemoteParseError("timeout", "MinerU：任务一小时内未完成")
            if job.get("status") == "running":
                # 服务端只报文件级进度；按耗时渐近逼近 0.9
                progress(0.1 + 0.8 * (1 - math.exp(-elapsed / 90)), "MinerU：解析中")
            else:
                progress(0.05, "MinerU：排队中")
            await asyncio.sleep(self._poll)
            job = await cli.json("GET", f"/v1/parse/jobs/{job['job_id']}")
        return job

    @staticmethod
    def _result_file(job: dict[str, Any]) -> dict[str, Any]:
        files = job.get("files") or []
        file = files[0] if files and isinstance(files[0], dict) else {}
        if job.get("status") in ("failed", "canceled") or file.get("status") == "failed":
            err = job.get("error") or file.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RemoteParseError("job_failed", f"MinerU：解析失败（{msg or job.get('status')}）")
        return file

    @staticmethod
    async def _cancel(cli: RemoteClient, job_id: str | None) -> None:
        """任务被取消时尽力通知服务端，失败不影响取消本身。"""
        if not job_id:
            return
        try:
            await asyncio.shield(
                asyncio.wait_for(cli.request("DELETE", f"/v1/parse/jobs/{job_id}"), 5)
            )
        except (RemoteParseError, TimeoutError, asyncio.CancelledError):
            pass
