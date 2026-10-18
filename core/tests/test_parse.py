import asyncio
import json
import shutil
import time
from pathlib import Path

import pytest

from freeread.domain.ir.models import Document, validate_document
from freeread.infra.db.models import BlockRow, DocumentRow, ItemRow, TranslationRow
from freeread.infra.jobs.queue import JobStatus
from freeread.infra.parsers.pymupdf_fast import PyMuPDFFastNormalizer, PyMuPDFFastParser
from freeread.infra.parsers.registry import EngineSpec
from freeread.services.parse import EngineUnavailableError, _render_assets

SYNTHETIC = Path(__file__).parent / "fixtures" / "raw" / "synthetic.pdf"


async def noop(p, m=None):
    pass


def import_synthetic(ctx, tmp_path, name="synthetic.pdf", strip_metadata=False):
    src = tmp_path / "in" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    if strip_metadata:
        import pymupdf

        with pymupdf.open(SYNTHETIC) as d:
            d.set_metadata({})
            d.save(src)
    else:
        shutil.copyfile(SYNTHETIC, src)
    item_id, _ = ctx.library.import_file(src)
    return item_id, ctx.library.get_item(item_id).documents[0].doc_id


class FakeHQParser(PyMuPDFFastParser):
    """假装是高质量引擎：输出与 PyMuPDF 相同，引擎名不同。"""

    calls = 0

    async def parse(self, pdf, out_dir, progress):
        FakeHQParser.calls += 1
        raw = await super().parse(pdf, out_dir, progress)
        (out_dir / "engine.json").write_text(
            json.dumps({"engine": "mineru", "engine_version": "hq"})
        )
        return raw


@pytest.fixture
def fake_mineru(ctx):
    FakeHQParser.calls = 0
    ctx.parse.registry.engines["mineru"] = EngineSpec(
        "mineru", "MinerU", 2, FakeHQParser, PyMuPDFFastNormalizer(), lambda: True, heavy=True
    )


async def test_fast_parse_stores_ir_blocks_and_backfills_title(ctx, tmp_path):
    item_id, doc_id = import_synthetic(ctx, tmp_path, "scan_0001.pdf", strip_metadata=True)
    assert ctx.library.get_item(item_id).title == "scan_0001"

    reports = []
    outcome = await ctx.parse.run(doc_id, "pymupdf", lambda p, m=None: noop(reports.append(p)))
    assert outcome.status == "parsed" and outcome.blocks == 23 and outcome.problems == 0
    assert reports == sorted(reports)

    doc = Document.model_validate_json(ctx.parse.ir_path(doc_id).read_text(encoding="utf-8"))
    assert validate_document(doc) == []
    out = ctx.parse.get(doc_id)
    assert (out.parse_status, out.parser_engine, out.page_count) == ("ready", "pymupdf", 2)
    with ctx.sessions() as s:
        rows = s.query(BlockRow).filter_by(doc_id=doc_id).order_by(BlockRow.ord).all()
        assert [r.block_id for r in rows] == [b.id for b in doc.blocks]
        assert rows[0].anchors[0]["page"] == 0
        row = s.get(DocumentRow, doc_id)
        assert row.ir_path == f"documents/{doc_id}/ir.json"
        item = s.get(ItemRow, item_id)
        assert item.title == "A Synthetic Study of Layout Parsing"
        assert item.extra["title_source"] == "ir"
    assert (ctx.paths.document_dir(doc_id) / "raw" / "pymupdf" / "engine.json").is_file()


async def test_cached_renormalized_and_forced(ctx, tmp_path, monkeypatch):
    _, doc_id = import_synthetic(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)
    assert (await ctx.parse.run(doc_id, "pymupdf", noop)).status == "cached"

    spec = ctx.parse.registry.get("pymupdf")
    monkeypatch.setattr(spec.normalizer, "version", "0.2.0")

    def no_parse():
        raise AssertionError("raw output exists, should only re-normalize")

    monkeypatch.setattr(spec, "make_parser", no_parse)
    assert (await ctx.parse.run(doc_id, "pymupdf", noop)).status == "renormalized"
    assert ctx.parse.get(doc_id).normalizer_version == "0.2.0"

    monkeypatch.setattr(spec, "make_parser", PyMuPDFFastParser)
    assert (await ctx.parse.run(doc_id, "pymupdf", noop, force=True)).status == "parsed"


async def test_reparse_migrates_translations_and_marks_stale(ctx, tmp_path, fake_mineru):
    _, doc_id = import_synthetic(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)
    with ctx.sessions.begin() as s:
        blocks = s.query(BlockRow).filter_by(doc_id=doc_id).order_by(BlockRow.ord).all()
        common = {
            "doc_id": doc_id,
            "lang": "zh-CN",
            "model": "p/m",
            "prompt_version": "translate@1",
        }
        s.add(TranslationRow(block_id=blocks[1].block_id, text="段落一", **common))
        s.add(TranslationRow(block_id="b_9999", text="已不存在的块", **common))
        moved_text = blocks[1].text

    outcome = await ctx.parse.run(doc_id, "mineru", noop)
    assert (outcome.migrated, outcome.stale) == (1, 1)
    assert ctx.parse.get(doc_id).parser_engine == "mineru"
    with ctx.sessions() as s:
        t = s.query(TranslationRow).filter_by(text="段落一").one()
        assert (
            s.query(BlockRow).filter_by(doc_id=doc_id, block_id=t.block_id).one().text == moved_text
        )
        gone = s.query(TranslationRow).filter_by(text="已不存在的块").one()
        assert gone.status == "stale" and not gone.is_active
        assert gone.block_id.startswith("stale:")

    # 自动流程不会用快速模式覆盖高质量结果
    assert (await ctx.parse.run(doc_id, "pymupdf", noop)).status == "skipped"


async def test_same_document_parses_are_serialized(ctx, tmp_path, fake_mineru):
    _, doc_id = import_synthetic(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)
    # 手动强制快速重解析与 MinerU 升级同时进行：都要成功，最终结果一致
    fast, hq = await asyncio.gather(
        ctx.parse.run(doc_id, "pymupdf", noop, force=True),
        ctx.parse.run(doc_id, "mineru", noop),
    )
    assert fast.status == "parsed" and hq.status == "parsed"
    out = ctx.parse.get(doc_id)
    assert (out.parse_status, out.parser_engine) == ("ready", "mineru")
    ir = Document.model_validate_json(ctx.parse.ir_path(doc_id).read_text(encoding="utf-8"))
    with ctx.sessions() as s:
        assert s.query(BlockRow).filter_by(doc_id=doc_id).count() == len(ir.blocks)


async def test_first_failure_marks_failed_but_failed_upgrade_keeps_ready(
    ctx, tmp_path, fake_mineru
):
    _, doc_id = import_synthetic(ctx, tmp_path)

    class Boom(PyMuPDFFastParser):
        async def parse(self, pdf, out_dir, progress):
            raise RuntimeError("engine crashed")

    spec = ctx.parse.registry.get("pymupdf")
    good = spec.make_parser
    spec.make_parser = Boom
    with pytest.raises(RuntimeError):
        await ctx.parse.run(doc_id, "pymupdf", noop)
    assert ctx.parse.get(doc_id).parse_status == "failed"

    spec.make_parser = good
    await ctx.parse.run(doc_id, "pymupdf", noop)
    ctx.parse.registry.get("mineru").make_parser = Boom
    with pytest.raises(RuntimeError):
        await ctx.parse.run(doc_id, "mineru", noop)
    out = ctx.parse.get(doc_id)
    assert (out.parse_status, out.parser_engine) == ("ready", "pymupdf")


async def test_missing_pdf_and_unavailable_engine(ctx, tmp_path):
    _, doc_id = import_synthetic(ctx, tmp_path)
    with pytest.raises(EngineUnavailableError):
        await ctx.parse.run(doc_id, "mineru", noop)
    (ctx.paths.document_dir(doc_id) / "source.pdf").unlink()
    with pytest.raises(FileNotFoundError):
        await ctx.parse.run(doc_id, "pymupdf", noop)


async def test_job_chain_fast_then_hq(ctx, tmp_path, fake_mineru):
    from freeread.infra.jobs.worker import JobWorker

    ctx.bus.bind_loop(asyncio.get_running_loop())
    worker = JobWorker(ctx.jobs, ctx.bus, poll_interval=0.05)
    worker.register("parse", ctx.parse.run_parse_job, concurrency=2)
    worker.register("parse_hq", ctx.parse.run_parse_hq_job)
    events = []
    async with ctx.bus.subscribe() as sub:
        _, doc_id = import_synthetic(ctx, tmp_path)  # 导入时已建 parse 任务
        await worker.start()
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                hq = ctx.jobs.list(kind="parse_hq")
                if hq and hq[0].status == JobStatus.DONE:
                    break
                await asyncio.sleep(0.05)
        finally:
            await worker.stop()
        while not sub.queue.empty():
            e = sub.queue.get_nowait()
            if e.type == "document":
                events.append((e.data["parse_status"], e.data["parser_engine"]))

    assert ctx.parse.get(doc_id).parser_engine == "mineru"
    assert FakeHQParser.calls == 1
    assert ("ready", "pymupdf") in events and events[-1] == ("ready", "mineru")
    parse_job = ctx.jobs.list(kind="parse")[0]
    assert parse_job.status == JobStatus.DONE and "23 个块" in parse_job.message


async def test_chain_respects_settings(ctx, tmp_path, fake_mineru):
    _, doc_id = import_synthetic(ctx, tmp_path)
    settings = ctx.settings.get()
    ctx.settings.put(settings.model_copy(update={"parse_engine": "pymupdf"}))
    assert ctx.parse._chain_hq(doc_id) is None
    ctx.settings.put(settings)
    job = ctx.parse._chain_hq(doc_id)
    assert job.kind == "parse_hq" and job.payload == {"doc_id": doc_id, "engine": "mineru"}
    assert ctx.parse._chain_hq(doc_id) is None  # 已有排队中的 parse_hq


def test_render_assets_crops_figures(tmp_path):
    from freeread.domain.ir.models import BlockType
    from freeread.infra.parsers.normalize_common import RawBlock, build_document

    doc, _ = build_document(
        [RawBlock(BlockType.FIGURE, 0, (72, 72, 272, 172))],
        pdf_sha256="ab" * 32,
        pages=[(612, 792)],
        engine="t",
        engine_version="0",
    )
    out = tmp_path / "assets"
    out.mkdir()
    (out / "stale.png").write_bytes(b"old")
    _render_assets(doc, SYNTHETIC, out)
    asset = doc.assets[0]
    assert sorted(p.name for p in out.iterdir()) == ["a_0000.png"]
    assert (asset.width_px, asset.height_px) == (417, 209)


def wait_job(client, job_id, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def test_documents_api(client, tmp_path):
    src = tmp_path / "paper.pdf"
    shutil.copyfile(SYNTHETIC, src)
    item = client.post("/library/import-file", json={"path": str(src)}).json()["item"]
    doc_id = item["documents"][0]["doc_id"]

    engines = {e["name"]: e for e in client.get("/parsers").json()}
    assert engines["pymupdf"]["available"] and not engines["mineru"]["available"]
    assert client.get("/documents/d_0000000000000000").status_code == 404

    parse_job = next(j for j in client.get("/jobs", params={"kind": "parse"}).json())
    assert wait_job(client, parse_job["id"])["status"] == "done"
    assert client.get(f"/documents/{doc_id}").json()["parse_status"] == "ready"

    ir = client.get(f"/documents/{doc_id}/ir")
    assert ir.status_code == 200 and ir.json()["doc_id"] == doc_id
    pdf = client.get(f"/documents/{doc_id}/pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert client.get(f"/documents/{doc_id}/assets/..%2Fir.json").status_code == 404
    assert client.get(f"/documents/{doc_id}/assets/a_0000.png").status_code == 404

    assert client.post(f"/documents/{doc_id}/parse", json={"engine": "nope"}).status_code == 422
    assert client.post(f"/documents/{doc_id}/parse", json={"engine": "mineru"}).status_code == 409
    again = client.post(f"/documents/{doc_id}/parse", json={"engine": "pymupdf"})
    assert again.status_code == 202 and again.json()["payload"]["force"] is True
    assert wait_job(client, again.json()["id"])["status"] == "done"


def test_ir_is_409_before_parse(ctx, tmp_path):
    from fastapi.testclient import TestClient

    from freeread.main import create_app

    app = create_app(data_dir=tmp_path / "other")
    c = TestClient(app)  # 不进入 lifespan，worker 不运行，解析任务一直排队
    src = tmp_path / "x.pdf"
    shutil.copyfile(SYNTHETIC, src)
    doc_id = c.post("/library/import-file", json={"path": str(src)}).json()["item"]["documents"][0][
        "doc_id"
    ]
    assert c.get(f"/documents/{doc_id}/ir").status_code == 409
    app.state.ctx.close()
