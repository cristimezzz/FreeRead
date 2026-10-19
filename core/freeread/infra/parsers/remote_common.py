"""远程解析服务（自部署 / 云端 MinerU、docling-serve）共用的 HTTP 工具。见 ADR-0008。

- 本机 / 局域网地址不走系统代理（trust_env=False），公网地址沿用系统代理设置；
- 网络错误有限次重试，HTTP 错误不重试；
- 错误消息里的 API Key 一律替换为 ***。
"""

import asyncio
import ipaddress
import json
import random
from typing import Any, Self
from urllib.parse import urlparse

import httpx

TIMEOUT = httpx.Timeout(120.0, connect=30.0)
TRANSPORT_ATTEMPTS = 3
_BODY_SNIPPET = 300


class RemoteParseError(RuntimeError):
    """远程解析失败。code：unauthorized / http_error / transport / job_failed / bad_output / timeout。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _host(url: str) -> str | None:
    return urlparse(url if "://" in url else f"http://{url}").hostname


def is_local_url(url: str) -> bool:
    """本机、局域网或链路本地地址：PDF 不出本地网络，无需隐私确认（ADR-0008）。"""
    host = (_host(url) or "").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def is_loopback_url(url: str) -> bool:
    """与 sidecar 同一台机器：服务可以直接读本地文件路径。"""
    host = (_host(url) or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class RemoteClient:
    """对一个服务地址的薄封装：拼 URL、加鉴权头、重试网络错误、检查状态码、脱敏。"""

    def __init__(
        self,
        service: str,
        base_url: str,
        auth_headers: dict[str, str],
        secret: str | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.service = service
        self.base_url = base_url.rstrip("/")
        self._auth = auth_headers
        self._secret = secret
        self._http = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            trust_env=not is_local_url(self.base_url),
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    def redact(self, text: str) -> str:
        return text.replace(self._secret, "***") if self._secret else text

    def url(self, path: str) -> str:
        return path if "://" in path else f"{self.base_url}{path}"

    async def request(
        self, method: str, path: str, *, auth: bool = True, **kwargs: Any
    ) -> httpx.Response:
        """发请求并检查状态码；auth=False 用于预签名上传地址等第三方 URL（不能带密钥）。"""
        headers = {**(self._auth if auth else {}), **kwargs.pop("headers", {})}
        for attempt in range(1, TRANSPORT_ATTEMPTS + 1):
            try:
                response = await self._http.request(
                    method, self.url(path), headers=headers, **kwargs
                )
                break
            except httpx.TransportError as exc:
                if attempt == TRANSPORT_ATTEMPTS:
                    raise RemoteParseError(
                        "transport",
                        f"{self.service}: 无法连接 {self.base_url}（{type(exc).__name__}: "
                        f"{self.redact(str(exc))}）",
                    ) from None
                await asyncio.sleep(0.25 * 2 ** (attempt - 1) * (0.5 + random.random()))
        if response.status_code >= 400:
            snippet = self.redact(response.text[:_BODY_SNIPPET])
            code = "unauthorized" if response.status_code in (401, 403) else "http_error"
            raise RemoteParseError(code, f"{self.service}: HTTP {response.status_code}: {snippet}")
        return response

    async def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request(method, path, **kwargs)
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            raise RemoteParseError(
                "bad_output", f"{self.service}: {path} 返回的不是 JSON"
            ) from None
        if not isinstance(data, dict):
            raise RemoteParseError("bad_output", f"{self.service}: {path} 返回的不是 JSON 对象")
        return data
