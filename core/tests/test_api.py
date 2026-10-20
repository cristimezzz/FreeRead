import asyncio

from fastapi.testclient import TestClient

from freeread.api.sse import bus_stream
from freeread.infra.jobs.events import EventBus
from freeread.main import create_app
from tests.conftest import AUTH

PROVIDER = {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1"}


def test_settings_defaults(client):
    s = client.get("/settings").json()
    assert s["target_lang"] == "zh-CN"
    assert s["parse_engine"] == "auto"
    assert s["parse_device"] == "auto"
    assert s["appearance"]["theme_mode"] == "system"
    assert s["appearance"]["seed_color"] == "#D97757"
    assert s["providers"] == [] and s["routes"] == {}


def test_settings_roundtrip_persists(client, tmp_path):
    s = client.get("/settings").json()
    s["appearance"]["seed_color"] = "#00639b"
    s["providers"] = [PROVIDER]
    s["routes"] = {"translate": {"provider_id": "deepseek", "model": "deepseek-chat"}}
    resp = client.put("/settings", json=s)
    assert resp.status_code == 200, resp.text
    assert resp.json()["appearance"]["seed_color"] == "#00639B"

    # 新进程（同一数据目录）读到同样的设置
    with TestClient(create_app(token="secret", data_dir=tmp_path / "data"), headers=AUTH) as c2:
        s2 = c2.get("/settings").json()
    assert s2["providers"][0]["kind"] == "openai_compatible"
    assert s2["routes"]["translate"]["model"] == "deepseek-chat"


def test_settings_validation(client):
    s = client.get("/settings").json()
    bad_route = s | {"routes": {"translate": {"provider_id": "nope", "model": "m"}}}
    assert client.put("/settings", json=bad_route).status_code == 422
    # 密钥不允许进设置
    with_key = s | {"providers": [PROVIDER | {"api_key": "sk-xxx"}]}
    assert client.put("/settings", json=with_key).status_code == 422
    # M3 时期的默认紫色换成新的默认强调色（ADR-0007）
    legacy = s | {"appearance": s["appearance"] | {"seed_color": "#6750a4"}}
    assert client.put("/settings", json=legacy).json()["appearance"]["seed_color"] == "#D97757"
    bad_color = s | {"appearance": s["appearance"] | {"seed_color": "red"}}
    assert client.put("/settings", json=bad_color).status_code == 422
    assert client.put("/settings", json=s | {"parse_device": "tpu"}).status_code == 422
    assert client.put("/settings", json=s | {"parse_device": "gpu"}).json()["parse_device"] == "gpu"


def test_settings_invalid_stored_value_falls_back_to_default(client):
    ctx = client.app.state.ctx
    from freeread.infra.db.models import SettingRow

    with ctx.sessions.begin() as s:
        s.merge(SettingRow(key="parse_engine", value="removed_engine"))
        s.merge(SettingRow(key="target_lang", value="en"))
    s = client.get("/settings").json()
    assert s["parse_engine"] == "auto" and s["target_lang"] == "en"


def test_jobs_api(client):
    ctx = client.app.state.ctx
    job = ctx.jobs.enqueue("no_handler_yet", {"doc_id": "d_1"})

    listed = client.get("/jobs", params={"status": "queued"}).json()
    assert [j["id"] for j in listed] == [job.id]
    assert client.get(f"/jobs/{job.id}").json()["payload"] == {"doc_id": "d_1"}
    assert client.get("/jobs/missing").status_code == 404

    cancelled = client.post(f"/jobs/{job.id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert client.get("/jobs", params={"status": "queued"}).json() == []


async def test_bus_stream_formats_sse():
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    disconnected = False

    async def is_disconnected():
        return disconnected

    stream = bus_stream(bus, {"job"}, is_disconnected, heartbeat=0.05)
    assert await anext(stream) == "event: ready\ndata: {}\n\n"
    bus.publish("translation", {"ignored": True})
    bus.publish("job", {"id": "j1", "message": "解析中"})
    assert await anext(stream) == 'event: job\ndata: {"id": "j1", "message": "解析中"}\n\n'
    assert await anext(stream) == ": ping\n\n"
    disconnected = True
    assert [chunk async for chunk in stream] == []
    assert bus.subscriber_count == 0


async def test_bus_publish_from_worker_thread():
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    async with bus.subscribe() as sub:
        await asyncio.to_thread(bus.publish, "job", {"id": "x"})
        event = await asyncio.wait_for(sub.get(), 1)
    assert event.data == {"id": "x"}


def test_consent_is_revoked_when_provider_base_url_changes_or_is_removed(client):
    s = client.get("/settings").json()
    s["providers"] = [PROVIDER]
    s["consented_providers"] = ["deepseek"]
    assert client.put("/settings", json=s).json()["consented_providers"] == ["deepseek"]

    # 同意是针对某个地址给的；换了地址要重新询问
    s["providers"] = [{**PROVIDER, "base_url": "https://evil.example/v1"}]
    assert client.put("/settings", json=s).json()["consented_providers"] == []

    # 服务被删除后，同意也一并作废
    s["consented_providers"] = ["deepseek"]
    assert client.put("/settings", json=s).json()["consented_providers"] == ["deepseek"]
    s["providers"] = []
    assert client.put("/settings", json=s).json()["consented_providers"] == []
