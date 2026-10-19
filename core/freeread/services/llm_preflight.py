"""调用大模型前的检查：路由、密钥、隐私确认。翻译、总结（以后还有问答）共用。

首次向某个 provider 发送文档内容前必须由用户确认（settings.consented_providers，
architecture §10）；没确认时抛 code=consent_required，前端弹确认框后重试。
"""

from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.errors import RouteNotConfigured
from freeread.infra.llm.gateway import TaskKind
from freeread.services.settings import SettingsService


class PreflightError(Exception):
    """请求无法进行。code：route_not_configured / missing_api_key / consent_required。"""

    def __init__(self, code: str, message: str, provider_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.provider_id = provider_id


def check_provider(
    gateway: DefaultGateway, settings: SettingsService, task: TaskKind
) -> tuple[str, str]:
    """返回 (provider_id, model)。不满足时抛 PreflightError。"""
    current = settings.get()
    try:
        provider_id, model = gateway.route(task)
    except RouteNotConfigured as e:
        raise PreflightError("route_not_configured", str(e)) from e
    provider = next((p for p in current.providers if p.id == provider_id), None)
    if provider is None:
        raise PreflightError("route_not_configured", f"provider {provider_id!r} 不存在")
    if provider.kind != "ollama" and not gateway.secrets.has(provider_id):
        raise PreflightError("missing_api_key", f"provider {provider_id!r} 没有 API Key")
    if provider_id not in current.consented_providers:
        raise PreflightError(
            "consent_required",
            f"向 {provider.name} 发送文档内容前需要确认",
            provider_id=provider_id,
        )
    return provider_id, model
