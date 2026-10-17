"""LLM 调用的错误类型。消息里不得出现 API Key（provider 构造错误前先经 SecretStore.redact）。"""


class LLMError(Exception):
    """LLM 调用失败的基类。"""


class RouteNotConfigured(LLMError):
    """该任务类型没有配置 provider/model，或路由指向的 provider 不存在。"""


class MissingAPIKey(LLMError):
    """provider 需要密钥但 SecretStore 里没有。"""


class ProviderError(LLMError):
    """provider 返回了不可重试的错误（4xx、响应格式不对等）。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryableError(ProviderError):
    """429 / 5xx / 网络错误：Gateway 会指数退避后重试。"""

    def __init__(
        self, message: str, status_code: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message, status_code)
        self.retry_after = retry_after
