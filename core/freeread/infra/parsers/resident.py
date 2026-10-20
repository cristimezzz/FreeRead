"""常驻解析 worker 的客户端：MinerU 冷启动约 40 秒，不能每篇文档新起一个进程（ADR-0003）。

- 懒启动：第一次 parse 时才拉起 worker 进程；
- 复用：同一进程逐篇处理（一次一篇，加锁）；
- 空闲 idle_timeout 秒后自动退出，释放显存；
- worker 崩溃或调用被取消时结束进程，下次 parse 重新启动。
协议见 scripts/engines/resident_worker.py。
"""

import asyncio
import contextlib
import json
import logging
from itertools import count
from pathlib import Path

from freeread.infra.parsers.base import ParserCaps, ProgressCb, RawLayout
from freeread.infra.parsers.subprocess_engine import engine_env, engine_python, scripts_dir

log = logging.getLogger(__name__)

DEFAULT_IDLE_TIMEOUT = 600.0
READY_TIMEOUT = 300.0  # 首次导入 torch / 模型可能很慢


class WorkerError(RuntimeError):
    pass


class ResidentEngineParser:
    def __init__(
        self,
        name: str,
        caps: ParserCaps,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        log_path: Path | None = None,
        options: dict | None = None,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        self.name = name
        self.version = "resident"
        self._caps = caps
        self._command = command
        self._env = env
        self._log_path = log_path
        self._options = options or {}
        self._idle_timeout = idle_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._log_file = None
        self._lock = asyncio.Lock()
        self._ids = count(1)
        self._idle_task: asyncio.Task[None] | None = None

    def capabilities(self) -> ParserCaps:
        return self._caps

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout:
        async with self._lock:
            if self._idle_task:
                self._idle_task.cancel()
                self._idle_task = None
            try:
                if not self.running:
                    progress(0.0, f"{self.name}: 启动解析引擎")
                    await self._start()
                progress(0.05, f"{self.name}: 解析中")
                version = await self._request(pdf, out_dir)
            except BaseException:
                # 崩溃、协议错误或任务被取消：进程状态不可信，直接结束，下次重启
                await self._stop()
                raise
            self._idle_task = asyncio.create_task(self._idle_exit())
        progress(1.0, f"{self.name}: done")
        return RawLayout(engine=self.name, engine_version=version, raw_dir=out_dir, data=None)

    async def _start(self) -> None:
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self._log_path.open("ab")
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            env=self._env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self._log_file or asyncio.subprocess.DEVNULL,
        )
        msg = await asyncio.wait_for(self._read(), READY_TIMEOUT)
        if msg.get("event") != "ready":
            raise WorkerError(f"{self.name} worker: unexpected first message {msg}")
        log.info("%s worker started (pid %s)", self.name, self._proc.pid)

    async def _read(self) -> dict:
        assert self._proc and self._proc.stdout
        line = await self._proc.stdout.readline()
        if not line:
            code = await self._proc.wait()
            raise WorkerError(f"{self.name} worker exited with {code}; see {self._log_path}")
        return json.loads(line)

    async def _request(self, pdf: Path, out_dir: Path) -> str:
        assert self._proc and self._proc.stdin
        out_dir.mkdir(parents=True, exist_ok=True)
        req_id = str(next(self._ids))
        req = {"id": req_id, "pdf": str(pdf), "out_dir": str(out_dir), "options": self._options}
        self._proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()
        while True:
            msg = await self._read()
            if msg.get("id") != req_id:
                continue
            if msg.get("event") == "done":
                return msg.get("engine_version") or "unknown"
            if msg.get("event") == "error":
                raise WorkerError(f"{self.name}: {msg.get('message')}")

    async def _idle_exit(self) -> None:
        await asyncio.sleep(self._idle_timeout)
        async with self._lock:
            log.info("%s worker idle for %.0fs, stopping", self.name, self._idle_timeout)
            await self._stop()

    async def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.returncode is None:
            if proc.stdin:
                proc.stdin.close()  # worker 读到 EOF 后自行退出
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    async def close(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_task
            self._idle_task = None
        await self._stop()


def mineru_resident(log_dir: Path | None = None) -> ResidentEngineParser:
    script = scripts_dir() / "mineru_worker.py"
    return ResidentEngineParser(
        "mineru",
        ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False),
        [str(engine_python("mineru")), str(script)],
        env=engine_env(),
        log_path=log_dir / "mineru-worker.log" if log_dir else None,
        options={"effort": "medium"},
    )
