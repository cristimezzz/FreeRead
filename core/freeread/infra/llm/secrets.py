"""API Key 的内存存储。见 docs/01-architecture.md §5.4。

密钥持久化在系统钥匙串，由 Rust 壳在启动 sidecar 时以环境变量 FREEREAD_SECRETS
（JSON `{provider_id: key}`）注入；运行中修改走 `PUT /llm/providers/{id}/key`。
Python 端只放内存：不落盘、不进日志、不进 /settings、不出现在异常消息里。
"""

import json
import logging
import os
import threading
from collections.abc import Mapping

ENV_VAR = "FREEREAD_SECRETS"
REDACTED = "***"
# 太短的值替换时容易误伤正常文本；真实密钥都远长于此。
_MIN_REDACT_LEN = 6

log = logging.getLogger(__name__)


class SecretStore:
    def __init__(self, initial: Mapping[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, str] = {k: v for k, v in (initial or {}).items() if v}

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "SecretStore":
        """读取并移除环境变量，避免它被继承给解析引擎等子进程。"""
        env = os.environ if environ is None else environ
        raw = env.pop(ENV_VAR, None)
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except ValueError:
            log.warning("%s is not valid JSON; ignored", ENV_VAR)
            return cls()
        if not isinstance(data, dict):
            log.warning("%s must be a JSON object; ignored", ENV_VAR)
            return cls()
        return cls({str(k): v for k, v in data.items() if isinstance(v, str)})

    def get(self, provider_id: str) -> str | None:
        with self._lock:
            return self._keys.get(provider_id)

    def has(self, provider_id: str) -> bool:
        return self.get(provider_id) is not None

    def set(self, provider_id: str, key: str) -> None:
        with self._lock:
            self._keys[provider_id] = key

    def delete(self, provider_id: str) -> None:
        with self._lock:
            self._keys.pop(provider_id, None)

    def provider_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._keys)

    def redact(self, text: str) -> str:
        """把文本里出现的任何已知密钥替换为 ***。"""
        with self._lock:
            values = sorted(self._keys.values(), key=len, reverse=True)
        for value in values:
            if len(value) >= _MIN_REDACT_LEN:
                text = text.replace(value, REDACTED)
        return text

    def __repr__(self) -> str:
        return f"SecretStore(providers={self.provider_ids()})"


class RedactingFilter(logging.Filter):
    """日志兜底：格式化后的消息里若含密钥则替换。挂在 handler 上。"""

    def __init__(self, store: SecretStore) -> None:
        super().__init__()
        self._store = store

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._store.redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and record.exc_info[1] is not None:
            # 异常文本在 handler 格式化时才生成，这里先格式化并脱敏，再去掉原始 exc_info。
            exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self._store.redact(exc_text)
            record.exc_info = None
        return True
