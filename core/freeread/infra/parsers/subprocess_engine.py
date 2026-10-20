"""在独立 Python 环境中以子进程运行解析引擎（见 ADR-0003）。

每个重型引擎（MinerU / Docling / Marker）有自己的虚拟环境，避免 torch 等依赖冲突；
引擎侧的薄包装脚本位于 scripts/engines/run_<engine>.py，只负责调用引擎并把原生输出写到 raw 目录。

环境的位置（engines_root）：开发时为仓库下的 .engines/（scripts/m0_setup_engines.sh 创建）；
打包版为数据目录下的 engines/，由应用内安装（installer.py）创建，见 AppContext.open。
打包版的包装脚本随 sidecar 放在 sys._MEIPASS/engines/（scripts/build_sidecar.ps1）。
"""

import asyncio
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from freeread.infra.parsers.base import ParserCaps, ProgressCb, RawLayout

REPO_ROOT = Path(__file__).resolve().parents[4]
FROZEN = bool(getattr(sys, "frozen", False))

_engines_root = REPO_ROOT / ".engines"


def engines_root() -> Path:
    return _engines_root


def set_engines_root(root: Path) -> None:
    global _engines_root
    _engines_root = root


def scripts_dir() -> Path:
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "engines"
    return REPO_ROOT / "scripts" / "engines"


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


# 设置里的解析设备（settings.parse_device）→ 引擎读取的环境变量值
DEVICE_ENV_VARS = ("MINERU_DEVICE_MODE", "DOCLING_DEVICE")
DEVICE_VALUES = {"gpu": "cuda", "cpu": "cpu"}


def engine_python(engine: str) -> Path:
    env = os.environ.get(f"FREEREAD_{engine.upper()}_PYTHON")
    if env:
        return Path(env)
    return venv_python(engines_root() / engine)


def engine_env(device: str = "auto") -> dict[str, str]:
    """模型与缓存统一放到 <engines_root>/cache/，并关闭遥测。与 scripts/engines/env.sh 保持一致。

    device：auto（引擎自行检测，有 CUDA 用 GPU）/ gpu / cpu。
    """
    cache = Path(os.environ.get("ENGINE_CACHE", engines_root() / "cache"))
    env = dict(os.environ)
    # 继承来的设备变量不能盖过用户在设置里的选择
    for var in DEVICE_ENV_VARS:
        env.pop(var, None)
    if device in DEVICE_VALUES:
        env.update(dict.fromkeys(DEVICE_ENV_VARS, DEVICE_VALUES[device]))
    env.update(
        {
            "ENGINE_CACHE": str(cache),
            "MINERU_HOME": str(cache / "mineru"),
            "HF_HOME": str(cache / "hf"),
            "TORCH_HOME": str(cache / "torch"),
            "XDG_CACHE_HOME": str(cache / "xdg"),
            "MODEL_CACHE_DIR": str(cache / "marker"),
            "DO_NOT_TRACK": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def engine_command(
    engine: str, pdf: Path, out_dir: Path, extra: list[str] | None = None
) -> list[str]:
    script = scripts_dir() / f"run_{engine}.py"
    return [str(engine_python(engine)), str(script), str(pdf), str(out_dir), *(extra or [])]


class SubprocessParser:
    def __init__(
        self,
        name: str,
        caps: ParserCaps,
        extra_args: list[str] | None = None,
        device: Callable[[], str] | None = None,
    ) -> None:
        self.name = name
        self.version = "subprocess"
        self._caps = caps
        self._extra = extra_args or []
        self._device = device or (lambda: "auto")

    def capabilities(self) -> ParserCaps:
        return self._caps

    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout:
        out_dir.mkdir(parents=True, exist_ok=True)
        progress(0.0, f"{self.name}: start")
        with (out_dir / "engine.log").open("wb") as log:
            proc = await asyncio.create_subprocess_exec(
                *engine_command(self.name, pdf, out_dir, self._extra),
                env=engine_env(self._device()),
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
            rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"{self.name} exited with {rc}; see {out_dir / 'engine.log'}")
        info = json.loads((out_dir / "engine.json").read_text(encoding="utf-8"))
        progress(1.0, f"{self.name}: done")
        return RawLayout(
            engine=self.name, engine_version=info["engine_version"], raw_dir=out_dir, data=None
        )
