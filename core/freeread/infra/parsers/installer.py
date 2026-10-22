"""应用内安装本机解析引擎（MinerU / Docling），见 ADR-0003 第 5 点。

引擎不随安装包分发，由用户在设置里点"安装"后下载到 <engines_root>/<engine>/ 独立环境：
1. 准备 uv：环境变量 FREEREAD_UV → 之前下载到 <root>/_uv/ 的 → PATH 上的 uv → 下载固定版本（sha256 校验）；
2. `uv venv --managed-python --relocatable` 建到 <root>/<engine>.partial（Python 由 uv 下载到 <root>/_python/）；
3. `uv pip install --torch-backend <...>` 安装固定版本的引擎包（与 Normalizer 适配的版本一致），
   默认 GPU 版 PyTorch，失败时退回 CPU 版（torch_backends）；
4. 导入检查通过后改名为 <root>/<engine>。engine_python() 在改名后才存在，装到一半不会被当作已安装。
模型权重不在这里下载：引擎首次解析时自己下载到 <root>/cache/（engine_env）。
"""

import asyncio
import logging
import os
import platform
import shutil
import sys
import tarfile
import zipfile
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from freeread.infra.embedding.downloader import DownloadItem, download_all
from freeread.infra.parsers.subprocess_engine import engine_env, engines_root, venv_python

log = logging.getLogger(__name__)

PYTHON_VERSION = "3.12"
# 版本与 Normalizer 开发、评测时一致（core/tests/fixtures/raw/<engine>/engine.json）
ENGINE_PACKAGES: dict[str, tuple[str, ...]] = {
    "mineru": ("mineru[torch]==4.0.12",),
    "docling": ("docling==2.140.0",),
}
IMPORT_CHECK = {
    "mineru": "import mineru.backend.analyze",
    "docling": "import docling.document_converter",
}

# 没检测到 NVIDIA 驱动时默认装的 CUDA 版本（驱动 ≥ 570 可用，支持到 RTX 50 系）
DEFAULT_CUDA_BACKEND = "cu128"
CUDA_MACHINES = {"amd64", "x86_64"}

UV_VERSION = "0.12.23"
# (平台, 架构) → (发布文件名, sha256, 字节数)；来自 GitHub release 的 digest
UV_ASSETS: dict[tuple[str, str], tuple[str, str, int]] = {
    ("win32", "amd64"): (
        "uv-x86_64-pc-windows-msvc.zip",
        "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90",
        18_043_715,
    ),
    ("win32", "arm64"): (
        "uv-aarch64-pc-windows-msvc.zip",
        "13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5",
        19_113_421,
    ),
    ("darwin", "arm64"): (
        "uv-aarch64-apple-darwin.tar.gz",
        "50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544",
        17_044_217,
    ),
    ("darwin", "x86_64"): (
        "uv-x86_64-apple-darwin.tar.gz",
        "960da44cb4b73685206ddd250b19e0a117fa41095710c1038f081f5cb613efb4",
        21_263_712,
    ),
    ("linux", "x86_64"): (
        "uv-x86_64-unknown-linux-gnu.tar.gz",
        "9167d72b3319674b6303c4cbe071854bba13ebdf3d76b1a7cbdc175471fb66d6",
        19_906_150,
    ),
    ("linux", "aarch64"): (
        "uv-aarch64-unknown-linux-gnu.tar.gz",
        "6524bd338177ed50d035d39354e12545e993bbeba2ecbddf0480c5b3a81d313f",
        18_965_616,
    ),
}
UV_URL = "https://github.com/astral-sh/uv/releases/download/{version}/{name}"
DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=120.0)

Report = Callable[[float, str], Awaitable[None]]


class InstallError(RuntimeError):
    pass


def torch_backends() -> list[str]:
    """依次尝试的 uv --torch-backend：默认装 GPU（CUDA）版，失败再退回 CPU 版。

    CUDA 版在没有可用 GPU 的机器上也能用 CPU 跑，所以没检测到显卡驱动时同样先装 GPU 版，
    之后装上驱动不必重装引擎。检测到 NVIDIA 驱动时用 auto，由 uv 选与驱动匹配的 CUDA 版本。
    macOS 与 ARM 版 Windows 没有 CUDA 版 PyTorch，交给 auto（CPU / MPS）。
    """
    if sys.platform not in ("win32", "linux") or platform.machine().lower() not in CUDA_MACHINES:
        return ["auto"]
    gpu = "auto" if shutil.which("nvidia-smi") else DEFAULT_CUDA_BACKEND
    return [gpu, "cpu"]


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


@dataclass
class EngineInstaller:
    root: Path | None = None  # 省略时用 engines_root()（随 set_engines_root 变化）
    log_dir: Path | None = None
    # 测试用：替换 uv 命令（例如 [sys.executable, "fake_uv.py"]）
    uv_command: list[str] | None = None

    @property
    def base(self) -> Path:
        return self.root or engines_root()

    async def install(self, engine: str, report: Report) -> None:
        if engine not in ENGINE_PACKAGES:
            raise InstallError(f"未知的解析引擎 {engine!r}")
        root = self.base
        root.mkdir(parents=True, exist_ok=True)
        final = root / engine
        partial = root / f"{engine}.partial"
        if partial.exists():
            await asyncio.to_thread(shutil.rmtree, partial)

        await report(0.0, "准备安装工具 uv")
        uv = await self._uv(report)
        env = self._uv_env(root)
        log_path = self.log_dir / f"engine-install-{engine}.log" if self.log_dir else None

        await report(0.05, f"下载 Python {PYTHON_VERSION} 并创建独立环境")
        await self._run(
            [*uv, "venv", "--managed-python", "--relocatable", "--python", PYTHON_VERSION,
             str(partial)],
            env, log_path, report, 0.05, "创建 Python 环境",
        )  # fmt: skip
        python = venv_python(partial)
        await report(0.15, "下载并安装引擎（含 PyTorch，可能有数 GB）")
        backends = torch_backends()
        for i, backend in enumerate(backends):
            try:
                await self._run(
                    [*uv, "pip", "install", "--python", str(python), "--torch-backend", backend,
                     *ENGINE_PACKAGES[engine]],
                    env, log_path, report, 0.15, "安装引擎",
                )  # fmt: skip
                break
            except InstallError:
                if i == len(backends) - 1:
                    raise
                log.warning("installing %s with torch backend %s failed; retrying", engine, backend)
                await report(0.15, "GPU 版 PyTorch 安装失败，改装 CPU 版")
        await report(0.95, "检查安装结果")
        await self._run(
            [str(python), "-c", IMPORT_CHECK[engine]],
            engine_env(),
            log_path,
            report,
            0.95,
            "检查安装结果",
        )
        if final.exists():  # 重新安装：替换旧环境
            await asyncio.to_thread(shutil.rmtree, final)
        partial.replace(final)
        log.info("installed %s into %s", engine, final)

    # ------------------------------------------------------------ uv

    async def _uv(self, report: Report) -> list[str]:
        if self.uv_command:
            return self.uv_command
        if env := os.environ.get("FREEREAD_UV"):
            return [env]
        local = self.base / "_uv" / _exe("uv")
        if local.is_file():
            return [str(local)]
        if found := shutil.which("uv"):
            return [found]
        await self._download_uv(local, report)
        return [str(local)]

    async def _download_uv(self, dest: Path, report: Report) -> None:
        key = (sys.platform, platform.machine().lower())
        if key not in UV_ASSETS:
            raise InstallError(f"不支持的平台 {key[0]}/{key[1]}，请手动安装 uv 后重试")
        name, sha256, size = UV_ASSETS[key]
        archive = dest.parent / name

        async def progress(done: int, total: int) -> None:
            mb = 1 << 20
            await report(0.05 * done / total, f"下载 uv：{done / mb:.0f} / {total / mb:.0f} MB")

        item = DownloadItem(UV_URL.format(version=UV_VERSION, name=name), archive, sha256, size)
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            await download_all([item], client, progress)
        await asyncio.to_thread(_extract_uv, archive, dest)
        archive.unlink(missing_ok=True)

    @staticmethod
    def _uv_env(root: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "UV_PYTHON_INSTALL_DIR": str(root / "_python"),
                "UV_CACHE_DIR": str(root / "_uv-cache"),
                "UV_NO_CONFIG": "1",  # 不读用户 / 项目的 uv.toml，免得被改了索引或 Python 偏好
                "UV_NO_PROGRESS": "1",
                "NO_COLOR": "1",
            }
        )
        return env

    # ------------------------------------------------------------ 子进程

    async def _run(
        self,
        cmd: list[str],
        env: dict[str, str],
        log_path: Path | None,
        report: Report,
        progress: float,
        step: str,
    ) -> None:
        """逐行转发输出作为任务消息；失败时把输出末尾带进错误信息。被取消时结束子进程。"""
        tail: deque[str] = deque(maxlen=20)
        log_file = log_path.open("a", encoding="utf-8") if log_path else None
        if log_file:
            log_file.write(f"$ {' '.join(cmd)}\n")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                tail.append(line)
                if log_file:
                    log_file.write(line + "\n")
                await report(progress, line[:200])
            rc = await proc.wait()
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        finally:
            if log_file:
                log_file.close()
        if rc != 0:
            detail = "\n".join(tail)
            raise InstallError(f"{step}失败（退出码 {rc}）：\n{detail}")


def _extract_uv(archive: Path, dest: Path) -> None:
    """只取出 uv 可执行文件（zip 在根目录，tar.gz 在 uv-<target>/ 下）。"""
    exe = dest.name
    tmp = dest.with_name(exe + ".part")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            member = next(n for n in z.namelist() if Path(n).name == exe)
            tmp.write_bytes(z.read(member))
    else:
        with tarfile.open(archive) as t:
            member = next(m for m in t.getmembers() if Path(m.name).name == exe and m.isfile())
            f = t.extractfile(member)
            assert f is not None
            tmp.write_bytes(f.read())
        tmp.chmod(0o755)
    tmp.replace(dest)
