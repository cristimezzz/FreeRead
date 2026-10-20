"""远程解析服务（ADR-0008）：MinerU v1 API、docling-serve 的 HTTP 流程，以及 API 模式的可用性。"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from freeread.infra.parsers.base import RawLayout
from freeread.infra.parsers.docling import DoclingNormalizer
from freeread.infra.parsers.docling_api import DoclingServeParser
from freeread.infra.parsers.mineru import MinerUNormalizer
from freeread.infra.parsers.mineru_api import MinerUApiParser
from freeread.infra.parsers.remote_common import RemoteParseError, is_local_url
from freeread.services.parse import EngineUnavailableError
from tests.test_parse import import_synthetic, noop

RAW = Path(__file__).parent / "fixtures" / "raw"
SYNTHETIC = RAW / "synthetic.pdf"
KEY = "sk-parser-abcdefghijkl"
MIDDLE = json.loads((RAW / "mineru" / "middle.json").read_text(encoding="utf-8"))
DOCLING = json.loads((RAW / "docling" / "docling.json").read_text(encoding="utf-8"))


def progress_log():
    seen: list[float] = []
    return seen, lambda p, msg: seen.append(p)


class FakeMinerU:
    """最小 MinerU v1 服务：上传、提交、轮询一次 running 后完成、下载。"""

    def __init__(self, *, sources=("file_id",), middle=None, fail=False, status=200):
        self.sources = list(sources)
        self.middle = MIDDLE if middle is None else middle
        self.fail = fail
        self.status = status
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, r: httpx.Request) -> httpx.Response:
        self.requests.append(r)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": f"bad key {KEY}"}})
        path, m = r.url.path, r.method
        if path == "/api/v1/health":
            return httpx.Response(
                200,
                json={"status": "ok", "version": "4.0.12", "features": {"sources": self.sources}},
            )
        if path == "/api/v1/uploads" and m == "POST":
            return httpx.Response(
                200,
                json={
                    "id": "up1",
                    "status": "pending",
                    "upload_url": "https://oss.example.com/put?sig=1",
                    "upload_headers": {"Content-Type": "application/pdf"},
                },
            )
        if r.url.host == "oss.example.com" and m == "PUT":
            return httpx.Response(200)
        if path == "/api/v1/uploads/up1/complete":
            return httpx.Response(200, json={"status": "completed", "file": {"id": "f_src"}})
        if path == "/api/v1/parse/jobs" and m == "POST":
            return httpx.Response(202, json={"job_id": "j1", "status": "queued", "files": []})
        if path == "/api/v1/parse/jobs/j1":
            self.polls += 1
            if self.polls == 1:
                return httpx.Response(200, json={"job_id": "j1", "status": "running", "files": []})
            if self.fail:
                return httpx.Response(
                    200,
                    json={
                        "job_id": "j1",
                        "status": "failed",
                        "files": [{"status": "failed", "error": {"message": "OOM"}}],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "job_id": "j1",
                    "status": "completed",
                    "files": [
                        {
                            "status": "completed",
                            "parse": {"parser_version": "4.0.12"},
                            "output_files": {"middle_json": {"file_id": "f_mid", "bytes": 1}},
                        }
                    ],
                },
            )
        if path == "/api/v1/files/f_mid/content":
            return httpx.Response(200, content=json.dumps(self.middle).encode())
        return httpx.Response(404, json={"error": {"message": f"unexpected {m} {path}"}})


def mineru(server, url="https://mineru.example.com/api", key=KEY):
    return MinerUApiParser(
        url, key, "basic", transport=httpx.MockTransport(server), poll_interval=0
    )


async def test_mineru_upload_parse_download(tmp_path):
    server = FakeMinerU()
    seen, cb = progress_log()
    raw = await mineru(server).parse(SYNTHETIC, tmp_path, cb)

    assert raw.engine_version == "4.0.12" and seen == sorted(seen) and seen[-1] == 1.0
    engine = json.loads((tmp_path / "engine.json").read_text())
    assert engine == {
        "engine": "mineru",
        "engine_version": "4.0.12",
        "transport": "api",
        "tier": "basic",
    }
    by_path = {(r.method, r.url.path): r for r in server.requests}
    submit = json.loads(by_path[("POST", "/api/v1/parse/jobs")].content)
    assert submit == {
        "files": [{"source": {"type": "file_id", "file_id": "f_src"}}],
        "output_formats": ["middle_json"],
        "tier": "basic",
    }
    assert by_path[("POST", "/api/v1/uploads")].headers["authorization"] == f"Bearer {KEY}"
    # 预签名上传地址不带密钥，内容是 PDF 原文
    put = by_path[("PUT", "/put")]
    assert "authorization" not in put.headers and put.content == SYNTHETIC.read_bytes()

    # 产物与本机引擎一致，现有 Normalizer 直接可用
    doc, _ = MinerUNormalizer().normalize(
        RawLayout("mineru", raw.engine_version, tmp_path, None), "0" * 64
    )
    assert doc.blocks and doc.parser.engine == "mineru"


async def test_mineru_loopback_local_source_skips_upload(tmp_path):
    server = FakeMinerU(sources=["file_id", "local"])
    p = MinerUApiParser(
        "http://127.0.0.1:8000/api",
        None,
        "basic",
        transport=httpx.MockTransport(server),
        poll_interval=0,
    )
    await p.parse(SYNTHETIC, tmp_path, lambda *a: None)
    paths = [r.url.path for r in server.requests]
    assert "/api/v1/uploads" not in paths
    body = json.loads(
        next(r for r in server.requests if r.url.path == "/api/v1/parse/jobs").content
    )
    assert body["files"][0]["source"] == {"type": "local", "path": str(SYNTHETIC.resolve())}
    assert all("authorization" not in r.headers for r in server.requests)


async def test_mineru_job_failure(tmp_path):
    with pytest.raises(RemoteParseError, match="OOM") as info:
        await mineru(FakeMinerU(fail=True)).parse(SYNTHETIC, tmp_path, lambda *a: None)
    assert info.value.code == "job_failed"
    assert not (tmp_path / "engine.json").exists()


async def test_mineru_unauthorized_redacts_key(tmp_path):
    with pytest.raises(RemoteParseError) as info:
        await mineru(FakeMinerU(status=401)).parse(SYNTHETIC, tmp_path, lambda *a: None)
    assert info.value.code == "unauthorized" and KEY not in str(info.value)


def _line(*spans):
    return {"bbox": [0, 0, 1, 1], "spans": [{"bbox": [0, 0, 1, 1], **s} for s in spans]}


# mineru.net（3.4.4，tier=standard）实际返回的形状：pdf_info、坐标为 pt、page_size
LEGACY = {
    "_backend": "hybrid",
    "_effort": "medium",
    "_ocr_enable": False,
    "_version_name": "3.4.4",
    "pdf_info": [
        {
            "page_idx": 0,
            "page_size": [600, 800],
            "preproc_blocks": [],
            "para_blocks": [
                {
                    "type": "title",
                    "level": 1,
                    "bbox": [60, 40, 540, 80],
                    "lines": [_line({"type": "text", "content": "A cGAS-mediated mechanism"})],
                },
                {
                    "type": "title",
                    "level": 2,
                    "bbox": [60, 100, 300, 115],
                    "lines": [_line({"type": "text", "content": "Results"})],
                },
                {
                    "type": "text",
                    "bbox": [60, 120, 300, 200],
                    "lines": [
                        _line({"type": "text", "content": "genomic instabil-"}),
                        _line(
                            {"type": "text", "content": "ity of "},
                            {"type": "inline_equation", "content": "x^{2}"},
                            {"type": "text", "content": " cells."},
                        ),
                    ],
                },
                {
                    "type": "text",
                    "merge_prev": True,
                    "bbox": [320, 420, 540, 440],
                    "lines": [_line({"type": "text", "content": "continued text."})],
                },
                {
                    "type": "interline_equation",
                    "bbox": [60, 210, 300, 230],
                    "lines": [_line({"type": "interline_equation", "content": "E = mc^2"})],
                },
                {
                    "type": "image",
                    "bbox": [60, 300, 300, 500],
                    "blocks": [
                        {
                            "type": "image_body",
                            "bbox": [60, 300, 300, 480],
                            "lines": [_line({"type": "image", "image_path": "remote.jpg"})],
                        },
                        {
                            "type": "image_caption",
                            "bbox": [60, 485, 300, 500],
                            "lines": [_line({"type": "text", "content": "Fig. 1. Repair."})],
                        },
                    ],
                },
                {
                    "type": "table",
                    "bbox": [320, 300, 540, 400],
                    "blocks": [
                        {
                            "type": "table_body",
                            "bbox": [320, 300, 540, 400],
                            "lines": [
                                _line(
                                    {
                                        "type": "table",
                                        "html": "<table><tr><td><eq>p</eq></td></tr></table>",
                                    }
                                )
                            ],
                        }
                    ],
                },
            ],
            "discarded_blocks": [
                {
                    "type": "header",
                    "bbox": [0, 0, 600, 20],
                    "lines": [_line({"type": "text", "content": "RESEARCH ARTICLE"})],
                },
                {
                    "type": "page_footnote",
                    "bbox": [60, 760, 540, 780],
                    "lines": [_line({"type": "text", "content": "*Corresponding author."})],
                },
            ],
        }
    ],
}


async def test_mineru_legacy_middle_json_upgraded(tmp_path):
    # mineru.net 仍返回 3.x 的 pdf_info：升级成 4.x 形状后，现有 Normalizer 直接可用
    raw = await mineru(FakeMinerU(middle=LEGACY)).parse(SYNTHETIC, tmp_path, lambda *a: None)
    assert raw.engine_version == "3.4.4"
    middle = json.loads((tmp_path / "middle.json").read_text(encoding="utf-8"))
    assert middle["extensions"]["docvortex_layout"]["pages"] == [
        {"page_idx": 0, "width_pt": 600.0, "height_pt": 800.0}
    ]
    doc, _ = MinerUNormalizer().normalize(
        RawLayout("mineru", raw.engine_version, tmp_path, None), "0" * 64
    )
    by_type = {}
    for b in doc.blocks:
        by_type.setdefault(b.type.value, []).append(b)
    assert by_type["title"][0].text == "A cGAS-mediated mechanism"
    assert by_type["heading"][0].text == "Results"
    para = by_type["paragraph"][0]
    # 行尾连字符接小写去掉；行内公式保留为 math 段
    assert para.text.startswith("genomic instability of ")
    assert any(i.kind == "math" and i.latex == "x^{2}" for i in para.inlines)
    assert by_type["equation"][0].latex == "E = mc^2"
    assert by_type["figure"][0].anchors[0].bbox == pytest.approx((60, 300, 300, 480))
    assert by_type["caption"][0].text == "Fig. 1. Repair."
    assert by_type["table"][0].html == "<table><tr><td><math>p</math></td></tr></table>"
    assert by_type["footnote"][0].text == "*Corresponding author."
    # merge_prev 的块并入上一段；页眉丢弃
    assert para.text.endswith("cells. continued text.") and len(by_type["paragraph"]) == 1
    assert "RESEARCH ARTICLE" not in json.dumps(doc.model_dump(mode="json"))


async def test_mineru_unknown_middle_json_rejected(tmp_path):
    for middle in ({"pdf_info": []}, {"something": "else"}):
        with pytest.raises(RemoteParseError, match="middle_json") as info:
            await mineru(FakeMinerU(middle=middle)).parse(SYNTHETIC, tmp_path, lambda *a: None)
        assert info.value.code == "bad_output"
    assert not (tmp_path / "middle.json").exists()


async def test_mineru_cancel_notifies_server(tmp_path):
    server = FakeMinerU()
    p = MinerUApiParser(
        "https://mineru.example.com/api",
        KEY,
        "basic",
        transport=httpx.MockTransport(server),
        poll_interval=10,
    )
    task = asyncio.create_task(p.parse(SYNTHETIC, tmp_path, lambda *a: None))
    while not any(r.url.path == "/api/v1/parse/jobs" for r in server.requests):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ("DELETE", "/api/v1/parse/jobs/j1") in [(r.method, r.url.path) for r in server.requests]


class FakeDocling:
    def __init__(self, *, result_status="success"):
        self.result_status = result_status
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, r: httpx.Request) -> httpx.Response:
        self.requests.append(r)
        path = r.url.path
        if path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "pending"})
        if path == "/v1/status/poll/t1":
            self.polls += 1
            status = "started" if self.polls == 1 else "success"
            return httpx.Response(200, json={"task_id": "t1", "task_status": status})
        if path == "/v1/result/t1":
            return httpx.Response(
                200,
                json={
                    "document": {"json_content": DOCLING},
                    "status": self.result_status,
                    "errors": [{"error_message": "bad page"}],
                },
            )
        if path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.9.0", "docling": "2.140.0"})
        return httpx.Response(404)


def docling(server):
    return DoclingServeParser(
        "http://192.168.1.20:5001", KEY, transport=httpx.MockTransport(server), poll_interval=0
    )


async def test_docling_serve_flow(tmp_path):
    server = FakeDocling()
    raw = await docling(server).parse(SYNTHETIC, tmp_path, lambda *a: None)
    assert raw.engine_version == "1.9.0"
    submit = server.requests[0]
    assert submit.headers["x-api-key"] == KEY
    body = submit.content
    assert b'name="to_formats"\r\n\r\njson' in body and b'name="do_formula_enrichment"' in body
    assert SYNTHETIC.read_bytes() in body
    doc, _ = DoclingNormalizer().normalize(
        RawLayout("docling", raw.engine_version, tmp_path, None), "0" * 64
    )
    assert doc.blocks and doc.parser.engine == "docling"


async def test_docling_serve_failure(tmp_path):
    with pytest.raises(RemoteParseError, match="bad page"):
        await docling(FakeDocling(result_status="failure")).parse(
            SYNTHETIC, tmp_path, lambda *a: None
        )


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:8000", True),
        ("http://localhost:5001", True),
        ("http://192.168.1.20:5001", True),
        ("http://10.0.0.5", True),
        ("http://[::1]:8000", True),
        ("https://mineru.net/api", False),
        ("https://8.8.8.8", False),
    ],
)
def test_is_local_url(url, local):
    assert is_local_url(url) is local


# ------------------------------------------------------------ 设置与可用性


def set_remote(ctx, engine, **cfg):
    s = ctx.settings.get()
    parsers = s.parsers.model_copy(
        update={engine: getattr(s.parsers, engine).model_copy(update={"mode": "api", **cfg})}
    )
    ctx.settings.put(s.model_copy(update={"parsers": parsers}))


def test_api_mode_availability(ctx):
    spec = ctx.parse.registry.get("mineru")
    assert (spec.location(), spec.unavailable_reason()) == ("local", "not_installed")

    set_remote(ctx, "mineru")
    assert (spec.location(), spec.unavailable_reason()) == ("api", "not_configured")

    set_remote(ctx, "mineru", base_url="http://192.168.1.20:8000")
    assert spec.available()  # 局域网地址无需确认
    assert isinstance(spec.make_parser(), MinerUApiParser)

    set_remote(ctx, "mineru", base_url="https://mineru.net/api")
    assert spec.unavailable_reason() == "consent_required"
    set_remote(ctx, "mineru", consented_url="https://mineru.net/api")
    assert spec.available()
    # 换地址后之前的确认作废
    set_remote(ctx, "mineru", base_url="https://other.example.com/api")
    assert spec.unavailable_reason() == "consent_required"


async def test_api_mode_without_consent_blocks_parse_and_chain(ctx, tmp_path):
    _, doc_id = import_synthetic(ctx, tmp_path)
    set_remote(ctx, "mineru", base_url="https://mineru.net/api")
    assert ctx.parse._chain_hq(doc_id) is None
    with pytest.raises(EngineUnavailableError, match="确认"):
        ctx.parse.request_parse(doc_id, "mineru")
    with pytest.raises(EngineUnavailableError):
        await ctx.parse.run(doc_id, "mineru", noop)


def test_parsers_api(client):
    engines = {e["name"]: e for e in client.get("/parsers").json()}
    assert engines["mineru"]["location"] == "local"
    assert engines["mineru"]["unavailable_reason"] == "not_installed"
    assert engines["mineru"]["has_key"] is False

    assert client.put("/parsers/mineru/key", json={"key": KEY}).status_code == 204
    assert client.get("/parsers").json()[2]["has_key"] is True
    assert client.app.state.ctx.secrets.get("parser-mineru") == KEY
    assert client.put("/parsers/marker/key", json={"key": KEY}).status_code == 422
    assert client.delete("/parsers/mineru/key").status_code == 204

    out = client.post("/parsers/docling/test").json()
    assert out["ok"] is False and out["error"] == "未填写服务地址"
    out = client.post("/parsers/docling/test", json={"base_url": "http://127.0.0.1:9"}).json()
    assert out["ok"] is False and out["error"]


def test_provider_id_cannot_use_parser_prefix(client):
    s = client.get("/settings").json()
    bad = s | {"providers": [{"id": "parser-mineru", "name": "x", "base_url": "http://x"}]}
    assert client.put("/settings", json=bad).status_code == 422


def test_settings_parsers_defaults_and_fallback(client):
    s = client.get("/settings").json()
    assert s["parsers"]["mineru"] == {
        "mode": "local",
        "base_url": "",
        "tier": "basic",
        "consented_url": None,
    }
    from freeread.infra.db.models import SettingRow

    with client.app.state.ctx.sessions.begin() as db:
        db.merge(SettingRow(key="parsers", value={"mineru": {"mode": "cloud"}}))
    assert client.get("/settings").json()["parsers"]["mineru"]["mode"] == "local"
