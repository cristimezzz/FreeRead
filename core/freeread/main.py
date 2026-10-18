"""Core Service 入口。

由 Tauri 壳以 sidecar 方式启动：
    freeread-core --port <随机端口> --token <会话 token> --parent-pid <壳进程 PID>
见 docs/01-architecture.md §3。
"""

import argparse
import asyncio
import logging
import os
import secrets
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from freeread import __version__
from freeread.api import documents, jobs, library, llm, settings, translate
from freeread.config import default_data_dir
from freeread.context import AppContext
from freeread.domain.ir.models import IR_SCHEMA_VERSION
from freeread.infra.llm.secrets import RedactingFilter

log = logging.getLogger(__name__)

# Tauri WebView 的源（Windows 为 http://tauri.localhost，macOS/Linux 为 tauri://localhost）
# 以及 `tauri dev` 的 Vite 开发服务器。前端请求带自定义头，需要通过 CORS 预检。
ALLOWED_ORIGINS = [
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:1420",
]


def create_app(token: str | None = None, data_dir: Path | None = None) -> FastAPI:
    """组装应用。打开数据库（必要时迁移）是同步完成的；任务 worker 随 lifespan 启停。"""

    def verify_token(x_freeread_token: str | None = Header(default=None)) -> None:
        if token is not None and x_freeread_token != token:
            raise HTTPException(status_code=401, detail="invalid session token")

    ctx = AppContext.open(data_dir or default_data_dir())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        ctx.bus.bind_loop(asyncio.get_running_loop())
        await ctx.worker.start()
        renorm = await asyncio.to_thread(ctx.parse.enqueue_renormalize)
        if renorm:
            log.info("queued %d re-normalize jobs (normalizer upgraded)", len(renorm))
        try:
            yield
        finally:
            await ctx.worker.stop()
            await ctx.parse.registry.close()
            await ctx.llm.aclose()
            ctx.close()

    app = FastAPI(
        title="FreeRead Core",
        version=__version__,
        dependencies=[Depends(verify_token)],
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "ir_schema_version": IR_SCHEMA_VERSION}

    app.include_router(jobs.router)
    app.include_router(library.router)
    app.include_router(documents.router)
    app.include_router(settings.router)
    app.include_router(llm.router)
    app.include_router(translate.router)
    return app


def _wait_parent_windows(pid: int) -> None:
    """阻塞直到 pid 对应的进程退出。持有进程句柄，不受 PID 复用影响。"""
    import ctypes
    from ctypes import wintypes

    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:  # 进程已不存在（或无权访问，按已退出处理）
        return
    try:
        kernel32.WaitForSingleObject(handle, INFINITE)
    finally:
        kernel32.CloseHandle(handle)


def _wait_parent_posix(pid: int, interval: float) -> None:
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass  # 进程存在，只是属于别的用户
        time.sleep(interval)


def watch_parent(pid: int, on_exit: Callable[[], None], interval: float = 1.0) -> threading.Thread:
    """看门狗：父进程（Tauri 壳）消失后调用 on_exit。

    壳正常退出时会主动 kill sidecar，Windows 上还有 Job Object 兜底；
    这里是第三道保险，覆盖 sidecar 被单独启动或 Job 失效的情况。
    """

    def target() -> None:
        if sys.platform == "win32":
            _wait_parent_windows(pid)
        else:
            _wait_parent_posix(pid, interval)
        on_exit()

    thread = threading.Thread(target=target, name="parent-watchdog", daemon=True)
    thread.start()
    return thread


def run(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="freeread-core")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=None, help="会话 token；省略时随机生成并打印")
    parser.add_argument("--parent-pid", type=int, default=None, help="父进程退出后自动退出")
    parser.add_argument(
        "--data-dir", type=Path, default=None, help="数据目录；默认 %%APPDATA%%/FreeRead"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    token = args.token or secrets.token_urlsafe(24)
    if args.token is None:
        print(f"session token: {token}")

    app = create_app(token, args.data_dir)
    config = uvicorn.Config(app, host="127.0.0.1", port=args.port)
    # 兜底：日志里出现已知密钥都替换为 ***。uvicorn 的 logger 不向 root 传播，
    # 要在 Config（它会配置日志）之后给各自的 handler 都挂上。
    redactor = RedactingFilter(app.state.ctx.secrets)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.addFilter(redactor)
    server = uvicorn.Server(config)

    if args.parent_pid is not None:

        def shutdown() -> None:
            server.should_exit = True
            # 优雅退出卡住时（如长请求未结束）强制结束
            timer = threading.Timer(5.0, os._exit, args=(0,))
            timer.daemon = True
            timer.start()

        watch_parent(args.parent_pid, shutdown)

    server.run()


if __name__ == "__main__":
    run()
