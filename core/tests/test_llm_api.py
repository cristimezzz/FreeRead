import json
import logging

import httpx
import pytest

from freeread.context import AppContext
from freeread.infra.llm.openai_compatible import OpenAICompatibleProvider
from freeread.infra.llm.secrets import ENV_VAR, RedactingFilter, SecretStore

KEY = "sk-very-secret-key-42"
SETTINGS_PROVIDERS = {
    "providers": [{"id": "ds", "name": "DeepSeek", "base_url": "https://api.deepseek.invalid/v1"}],
    "routes": {"translate": {"provider_id": "ds", "model": "deepseek-chat"}},
}


def configure(client) -> None:
    s = client.get("/settings").json() | SETTINGS_PROVIDERS
    assert client.put("/settings", json=s).status_code == 200


def use_transport(client, handler) -> None:
    """让 Gateway 的 provider 走 MockTransport。"""
    gw = client.app.state.ctx.llm
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gw._factory = lambda config, key: OpenAICompatibleProvider(
        config.id, config.base_url, key, client=http
    )


def test_key_put_delete_and_status(client):
    configure(client)
    assert client.get("/llm/providers").json() == [
        {"id": "ds", "name": "DeepSeek", "kind": "openai_compatible", "has_key": False}
    ]
    assert client.put("/llm/providers/ds/key", json={"key": KEY}).status_code == 204
    assert client.get("/llm/providers").json()[0]["has_key"] is True
    assert client.app.state.ctx.secrets.get("ds") == KEY

    # 密钥不出现在任何读接口里
    for path in ("/settings", "/llm/providers"):
        assert KEY not in client.get(path).text

    assert client.delete("/llm/providers/ds/key").status_code == 204
    assert client.get("/llm/providers").json()[0]["has_key"] is False


def test_key_validation(client):
    assert client.put("/llm/providers/BAD ID/key", json={"key": "x"}).status_code == 422
    assert client.put("/llm/providers/ds/key", json={"key": ""}).status_code == 422
    assert client.put("/llm/providers/ds/key", json={"key": "k", "x": 1}).status_code == 422


def test_settings_cannot_store_keys(client):
    s = client.get("/settings").json()
    s["providers"] = [SETTINGS_PROVIDERS["providers"][0] | {"api_key": KEY}]
    resp = client.put("/settings", json=s)
    assert resp.status_code == 422
    assert KEY not in json.dumps(client.get("/settings").json())


def test_provider_test_ok(client):
    configure(client)
    client.put("/llm/providers/ds/key", json={"key": KEY})
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    use_transport(client, handler)
    resp = client.post("/llm/providers/ds/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["model"] == "deepseek-chat" and body["error"] is None
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_provider_test_error_is_redacted(client):
    configure(client)
    client.put("/llm/providers/ds/key", json={"key": KEY})
    use_transport(client, lambda r: httpx.Response(401, json={"error": f"invalid key {KEY}"}))
    body = client.post("/llm/providers/ds/test", json={"model": "x"}).json()
    assert body["ok"] is False and body["model"] == "x"
    assert "401" in body["error"] and KEY not in body["error"]


def test_provider_test_missing_key_and_unknown_provider(client):
    configure(client)
    body = client.post("/llm/providers/ds/test").json()
    assert body["ok"] is False and "no API key" in body["error"]
    assert client.post("/llm/providers/nope/test").status_code == 404


def test_secret_store_from_env_removes_variable():
    env = {ENV_VAR: json.dumps({"ds": KEY, "bad": 1}), "OTHER": "1"}
    store = SecretStore.from_env(env)
    assert store.get("ds") == KEY and not store.has("bad")
    assert ENV_VAR not in env
    assert KEY not in repr(store)
    assert SecretStore.from_env({ENV_VAR: "not json"}).provider_ids() == []


def test_app_context_reads_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, json.dumps({"ds": KEY}))
    ctx = AppContext.open(tmp_path / "data")
    try:
        assert ctx.secrets.get("ds") == KEY
    finally:
        ctx.close()


def test_redacting_filter(caplog):
    store = SecretStore({"ds": KEY})
    logger = logging.getLogger("freeread.test.redact")
    caplog.handler.addFilter(RedactingFilter(store))
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("calling with %s", KEY)
            try:
                raise ValueError(f"boom {KEY}")
            except ValueError:
                logger.exception("failed")
    finally:
        caplog.handler.filters.clear()
    assert KEY not in caplog.text
    assert "calling with ***" in caplog.text and "boom ***" in caplog.text


@pytest.mark.parametrize("value", [KEY, f"prefix {KEY} suffix"])
def test_redact(value):
    assert KEY not in SecretStore({"a": KEY, "b": "abc"}).redact(value)
