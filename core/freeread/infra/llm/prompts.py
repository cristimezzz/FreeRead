"""提示词模板：core/prompts/*.yaml，Jinja2 渲染，以 `prompt_id@version` 引用。

修改模板内容时必须提升 version，缓存键包含 `prompt_id@version`，旧缓存随之失效（ADR-0005）。
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, Template, UndefinedError

from freeread.infra.llm.gateway import Message, TaskKind


def _default_prompts_dir() -> Path:
    """开发环境：core/freeread/infra/llm/prompts.py → core/prompts。
    PyInstaller 打包后：scripts/build_sidecar.ps1 把 core/prompts 放在 sys._MEIPASS/prompts。"""
    bundle = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and bundle:
        return Path(bundle) / "prompts"
    return Path(__file__).resolve().parents[3] / "prompts"


DEFAULT_PROMPTS_DIR = _default_prompts_dir()


class _OptionalUndefined(StrictUndefined):
    """未传的变量在 `{% if %}` / `{% for %}` 里按空处理（可选上下文，如 glossary），
    但直接输出（如漏传 text）仍然报错。"""

    def __bool__(self) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0


_env = Environment(undefined=_OptionalUndefined, autoescape=False)


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    task: TaskKind
    system: Template
    user: Template

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    def render(self, **variables: Any) -> list[Message]:
        """渲染为 [system, user]；system 为空时省略。"""
        try:
            system = self.system.render(variables).strip()
            user = self.user.render(variables).strip()
        except UndefinedError as exc:
            raise PromptError(f"{self.ref}: {exc}") from None
        messages = [Message("system", system)] if system else []
        return [*messages, Message("user", user)]


def _parse(path: Path) -> Prompt:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return Prompt(
            id=str(data["id"]),
            version=int(data["version"]),
            task=TaskKind(data["task"]),
            system=_env.from_string(data.get("system") or ""),
            user=_env.from_string(data["user"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PromptError(f"{path.name}: invalid prompt: {exc}") from None


class PromptRegistry:
    def __init__(self, prompts_dir: Path = DEFAULT_PROMPTS_DIR) -> None:
        self._prompts: dict[str, Prompt] = {}
        self._templates_dir = Path(prompts_dir) / "templates"
        if not Path(prompts_dir).is_dir():
            # 打包漏带 prompts/ 时启动即失败，而不是等到翻译时才报 unknown prompt
            raise PromptError(f"prompts directory not found: {prompts_dir}")
        for path in sorted(Path(prompts_dir).glob("*.yaml")):
            prompt = _parse(path)
            if prompt.id in self._prompts:
                raise PromptError(f"duplicate prompt id {prompt.id!r}")
            self._prompts[prompt.id] = prompt

    def get(self, prompt_id: str) -> Prompt:
        """接受 `translate` 或 `translate@1`；带版本时必须与文件中的版本一致。"""
        name, _, version = prompt_id.partition("@")
        prompt = self._prompts.get(name)
        if prompt is None:
            raise PromptError(f"unknown prompt {name!r}")
        if version and int(version) != prompt.version:
            raise PromptError(f"prompt {name!r} is at version {prompt.version}, not {version}")
        return prompt

    def ids(self) -> list[str]:
        return [p.ref for p in self._prompts.values()]

    def templates(self, kind: str) -> list[dict[str, Any]]:
        """templates/<kind>.yaml 里的模板列表（如总结模板）。不存在时返回空列表。"""
        path = self._templates_dir / f"{kind}.yaml"
        if not path.is_file():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("templates") or [])
