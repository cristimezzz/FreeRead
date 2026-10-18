"""M2 检索：全文索引、分块、向量索引、嵌入任务链与混合检索。"""

import asyncio
import hashlib
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from sqlalchemy import select, text

from freeread.infra.db.models import DocumentRow, EmbeddingChunkRow
from freeread.infra.embedding.downloader import DownloadError, DownloadItem, download_all
from freeread.infra.embedding.local import LocalEmbedder
from freeread.infra.embedding.registry import MODELS
from freeread.infra.jobs.worker import JobWorker
from freeread.infra.llm.fake import EMBED_DIM, FakeProvider
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.search import fts
from freeread.infra.search.chunker import MAX_TOKENS, approx_tokens, build_chunks
from freeread.infra.search.hybrid import rrf_merge
from freeread.infra.search.text import block_plain_text, expand_placeholders, table_text
from freeread.infra.search.vector_index import IndexMismatch, SqliteVecIndex
from freeread.services.settings import EmbeddingSettings, ModelRoute, ProviderConfig

SYNTHETIC = Path(__file__).parent / "fixtures" / "raw" / "synthetic.pdf"
DIM = 16


def bag_of_words(text: str) -> list[float]:
    """确定性的"语义"向量：词袋哈希到 DIM 维，有共同词的文本余弦更近。"""
    v = np.zeros(DIM, dtype=np.float32)
    for word in text.lower().split():
        v[int(hashlib.md5(word.strip(".,:;()").encode()).hexdigest(), 16) % DIM] += 1
    n = np.linalg.norm(v)
    return (v / n if n else v + 1 / np.sqrt(DIM)).tolist()


class FakeEmbedder(LocalEmbedder):
    def __init__(self, spec, models_dir):
        super().__init__(spec, models_dir)
        self.calls: list[list[str]] = []

    def is_downloaded(self) -> bool:
        return True

    def token_len(self, text: str) -> int:
        return approx_tokens(text)

    def embed(self, texts, kind="passage"):
        self.calls.append(list(texts))
        return [bag_of_words(t) for t in texts]


def use_fake_local(ctx) -> FakeEmbedder:
    spec = MODELS["multilingual-e5-small"]
    fake = FakeEmbedder(spec, ctx.paths.models)
    ctx.embed._embedders[spec.id] = fake
    return fake


async def import_doc(ctx, tmp_path, name="paper.pdf"):
    src = tmp_path / name
    shutil.copyfile(SYNTHETIC, src)
    item_id, _ = ctx.library.import_file(src)
    return ctx.library.get_item(item_id).documents[0].doc_id


async def noop(*_):
    pass


def job_ctx(payload):
    return SimpleNamespace(job=SimpleNamespace(id="j", payload=payload), report=noop)


# ---------------------------------------------------------------- 文本与分块


def test_plain_text_expands_math_and_drops_other_placeholders():
    inlines = [{"key": "EQ1", "kind": "math", "latex": "x^2"}, {"key": "C1", "kind": "cite"}]
    assert expand_placeholders("see ⟦EQ1⟧ and ⟦C1⟧.", inlines).split() == ["see", "x^2", "and", "."]
    assert block_plain_text("equation", "x", [], None) == ""
    assert block_plain_text("reference_entry", "Ref", [], None) == ""
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td><math>\\alpha</math></td><td>2</td></tr></table>"
    assert table_text(html).split() == ["A", "B", "\\alpha", "2"]


def B(i, type_="paragraph", text="word", section="s1"):
    return SimpleNamespace(
        block_id=f"b_{i:04d}", type=type_, section_id=section, text=text, inlines=[], html=None
    )


def test_chunks_merge_short_blocks_within_section_and_prefix_title():
    blocks = [
        B(0, "heading", "Intro"),
        B(1, text="alpha one"),
        B(2, text="beta two"),
        B(3, text="gamma", section="s2"),
    ]
    chunks = build_chunks(blocks, {"s1": "Intro", "s2": "Method"})
    assert [c.block_ids for c in chunks] == [["b_0001", "b_0002"], ["b_0003"]]
    assert chunks[0].text == "Intro\nalpha one\nbeta two"
    assert chunks[1].text.startswith("Method\n")
    assert chunks[0].text_hash != chunks[1].text_hash


def test_long_block_is_split_by_sentences():
    long = " ".join(f"Sentence number {i} has some words in it." for i in range(200))
    chunks = build_chunks([B(1, text=long), B(2, text="tail")], {})
    split = [c for c in chunks if c.block_ids == ["b_0001"]]
    assert len(split) > 1
    assert all(approx_tokens(c.text) <= MAX_TOKENS for c in split)
    assert chunks[-1].block_ids == ["b_0002"]


def test_rrf_merge_rewards_agreement():
    merged = rrf_merge({"fts": ["a", "b", "c"], "vector": ["c", "a", "a", "d"]})
    keys = [k for k, _, _ in merged]
    assert keys[0] == "a" and set(keys) == {"a", "b", "c", "d"}
    assert {k: src for k, _, src in merged}["c"] == ["fts", "vector"]


# ---------------------------------------------------------------- FTS 与向量索引


def test_fts_english_chinese_and_short_query_fallback(ctx):
    rows = [
        SimpleNamespace(block_id="b_0001", type="paragraph", text="AlphaFold predicts protein structure", inlines=[], html=None),
        SimpleNamespace(block_id="b_0002", type="paragraph", text="深度学习用于蛋白质结构预测", inlines=[], html=None),
        SimpleNamespace(block_id="b_0003", type="equation", text="protein", inlines=[], html=None),
    ]  # fmt: skip
    with ctx.sessions.begin() as s:
        s.add(DocumentRow(doc_id="d1", pdf_sha256="x"))
        s.flush()
        assert fts.replace_doc(s, "d1", rows) == 2
    with ctx.sessions() as s:
        hits = fts.search(s, "protein", "d1")
        assert [h.block_id for h in hits] == ["b_0001"]
        assert fts.HL_START + "protein" + fts.HL_END in hits[0].snippet
        assert [h.block_id for h in fts.search(s, "蛋白质", "d1")] == ["b_0002"]
        assert [h.block_id for h in fts.search(s, "结构", "d1")] == ["b_0002"]  # 2 字 → LIKE
        assert fts.search(s, "protein", "other") == []
        assert fts.search(s, '"; DROP', "d1") == []
        # 虚词不参与关键词匹配；中文标点按分隔符处理
        assert fts.query_terms("which protein is it?") == ["protein"]
        assert fts.query_terms("蛋白质，结构") == ["蛋白质", "结构"]


def test_vector_index_partition_mismatch_and_clear(ctx):
    index = SqliteVecIndex()
    with ctx.sessions.begin() as s:
        assert index.state(s) is None
        index.ensure(s, "m", 3)
        index.upsert(s, "a", [(1, [1, 0, 0]), (3, [0.7, 0.7, 0])])
        index.upsert(s, "b", [(2, [0, 1, 0])])
    with ctx.sessions() as s:
        assert [h.chunk_rowid for h in index.knn(s, [1, 0, 0], 5, "a")] == [1, 3]
        assert [h.chunk_rowid for h in index.knn(s, [1, 0, 0], 5)] == [1, 3, 2]
        assert index.vectors(s, [2])[2] == pytest.approx([0, 1, 0])
        with pytest.raises(IndexMismatch):
            index.ensure(s, "other", 3)
    with ctx.sessions.begin() as s:
        index.delete_doc(s, "a")
        assert [h.chunk_rowid for h in index.knn(s, [1, 0, 0], 5)] == [2]
        index.clear(s)
        assert index.state(s) is None and index.knn(s, [1, 0, 0], 5) == []
        index.ensure(s, "m2", 4)
    assert index.drop_unused(ctx.engine) == ["vec_chunks_3"]
    with ctx.sessions() as s:
        assert index.state(s).dim == 4


def test_virtual_tables_survive_migration_check(ctx):
    with ctx.engine.connect() as conn:
        names = set(conn.scalars(text("SELECT name FROM sqlite_master WHERE type='table'")))
    assert "blocks_fts" in names and "embedding_chunks" in names


# ---------------------------------------------------------------- 下载


async def test_download_resumes_and_verifies_sha256(tmp_path):
    payload = b"x" * 3000 + b"y" * 3000
    good = hashlib.sha256(payload).hexdigest()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers.get("range"))
        rng = request.headers.get("range")
        if rng:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            return httpx.Response(206, content=payload[start:])
        return httpx.Response(200, content=payload)

    dest = tmp_path / "m" / "model.onnx"
    dest.parent.mkdir()
    (dest.parent / "model.onnx.part").write_bytes(payload[:1000])
    seen = []

    async def progress(done, total):
        seen.append((done, total))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await download_all([DownloadItem("http://h/f", dest, good, len(payload))], client, progress)
        assert dest.read_bytes() == payload and requests == ["bytes=1000-"]
        assert seen[-1] == (len(payload), len(payload))

        bad = tmp_path / "bad.bin"
        with pytest.raises(DownloadError):
            await download_all([DownloadItem("http://h/f", bad, "0" * 64, len(payload))], client)
        assert not bad.exists() and not bad.with_name("bad.bin.part").exists()


# ---------------------------------------------------------------- 嵌入任务


async def test_embed_requires_downloaded_model(ctx, tmp_path):
    doc_id = await import_doc(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)
    assert ctx.embed.enqueue_embed(doc_id) is None  # 模型没下载：不排队
    status = ctx.embed.status()
    assert status.not_ready == "model_not_downloaded" and not status.downloaded
    assert status.size_bytes > 100_000_000
    job = ctx.embed.request_download()
    assert job.kind == "model_download" and ctx.embed.request_download().id == job.id


async def test_embed_job_writes_chunks_and_reuses_vectors(ctx, tmp_path):
    fake = use_fake_local(ctx)
    doc_id = await import_doc(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)
    job = ctx.embed.enqueue_embed(doc_id)
    assert job is not None and ctx.embed.enqueue_embed(doc_id).id == job.id  # 去重

    await ctx.embed.run_embed_job(job_ctx({"doc_id": doc_id}))
    with ctx.sessions() as s:
        assert s.get(DocumentRow, doc_id).embed_status == "ready"
        chunks = s.scalars(
            select(EmbeddingChunkRow).where(EmbeddingChunkRow.doc_id == doc_id)
        ).all()
        assert chunks and all(c.model == "local/multilingual-e5-small" for c in chunks)
        covered = {b for c in chunks for b in c.block_ids}
        assert "b_0020" not in covered  # 参考文献不嵌入
        assert "b_0002" not in covered  # 标题块只作前缀
        assert ctx.embed.index.state(s).dim == DIM
    first = sum(len(c) for c in fake.calls)
    assert first == len(chunks)

    # 内容不变的再次嵌入：全部复用
    fake.calls.clear()
    await ctx.embed.run_embed_job(job_ctx({"doc_id": doc_id}))
    assert fake.calls == []
    assert ctx.embed.status().docs_embedded == 1


async def test_parse_job_chains_embed(ctx, tmp_path):
    use_fake_local(ctx)
    ctx.bus.bind_loop(asyncio.get_running_loop())
    worker = JobWorker(ctx.jobs, ctx.bus, poll_interval=0.05)
    worker.register("parse", ctx.parse.run_parse_job, concurrency=2)
    worker.register("embed", ctx.embed.run_embed_job)
    doc_id = await import_doc(ctx, tmp_path)
    await worker.start()
    try:

        async def wait_ready():
            while ctx.parse.get(doc_id).embed_status != "ready":
                await asyncio.sleep(0.02)

        await asyncio.wait_for(wait_ready(), 10)
    finally:
        await worker.stop()
    kinds = [j.kind for j in ctx.jobs.list(None, None, 50)]
    assert "embed" in kinds


async def test_model_change_clears_index_and_requeues(ctx, tmp_path):
    use_fake_local(ctx)
    doc_id = await import_doc(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)
    await ctx.embed.run_embed_job(job_ctx({"doc_id": doc_id}))

    # 换成 provider 来源（8 维）但还没同意：不清空、不排队
    provider = FakeProvider("p1")
    s = ctx.settings.get()
    s = s.model_copy(
        update={
            "providers": [ProviderConfig(id="p1", name="P1", base_url="http://p1.invalid/v1")],
            "routes": {TaskKind.EMBED: ModelRoute(provider_id="p1", model="m-embed")},
            "embedding": EmbeddingSettings(source="provider"),
        }
    )
    ctx.settings.put(s)
    ctx.secrets.set("p1", "sk-test")
    ctx.llm._factory = lambda config, key: provider
    assert ctx.embed.enqueue_missing() == []
    assert ctx.embed.status().not_ready == "consent_required"

    ctx.settings.put(s.model_copy(update={"consented_providers": ["p1"]}))
    queued = ctx.embed.enqueue_missing()
    assert len(queued) == 1
    with ctx.sessions() as sess:
        assert ctx.embed.index.state(sess) is None
        assert sess.get(DocumentRow, doc_id).embed_status == "pending"
    await ctx.embed.run_embed_job(job_ctx({"doc_id": doc_id}))
    with ctx.sessions() as sess:
        assert ctx.embed.index.state(sess).dim == EMBED_DIM
        assert ctx.embed.index.state(sess).model == "p1/m-embed"
    assert provider.embed_calls


# ---------------------------------------------------------------- 检索


async def test_hybrid_search_without_and_with_vectors(ctx, tmp_path):
    doc_id = await import_doc(ctx, tmp_path)
    await ctx.parse.run(doc_id, "pymupdf", noop)

    res = await ctx.search.search_document(doc_id, "benchmark")
    assert res.modes == ["fts"]
    assert res.hits[0].block_id == "b_0010"  # "synthetic benchmark." 比长段落 bm25 更高
    assert res.hits[0].page == 0 and res.hits[0].sources == ["fts"]

    use_fake_local(ctx)
    await ctx.embed.run_embed_job(job_ctx({"doc_id": doc_id}))
    res = await ctx.search.search_document(doc_id, "stage accuracy")
    assert res.modes == ["fts", "vector"]
    assert res.hits[0].block_id == "b_0010"
    assert "vector" in res.hits[0].sources
    with ctx.sessions() as s:
        valid = set(s.scalars(text("SELECT block_id FROM blocks WHERE doc_id = :d"), {"d": doc_id}))
    assert {h.block_id for h in res.hits} <= valid

    with pytest.raises(LookupError):
        await ctx.search.search_document("nope", "x")
    assert (await ctx.search.search_document(doc_id, "   ")).hits == []


def test_search_and_embedding_api(client, tmp_path):
    src = tmp_path / "paper.pdf"
    shutil.copyfile(SYNTHETIC, src)
    r = client.post("/library/import-file", json={"path": str(src)})
    assert r.status_code == 200, r.text
    ctx = client.app.state.ctx
    doc_id = r.json()["item"]["documents"][0]["doc_id"]
    for _ in range(200):
        if ctx.parse.get(doc_id).parse_status == "ready":
            break
        time.sleep(0.05)
    r = client.get(f"/documents/{doc_id}/search", params={"q": "Precision"})
    assert r.status_code == 200
    body = r.json()
    assert body["modes"] == ["fts"] and body["hits"][0]["block_id"] == "b_0012"
    assert client.get("/documents/nope/search", params={"q": "x"}).status_code == 404

    st = client.get("/embedding/status").json()
    assert st["source"] == "local" and st["not_ready"] == "model_not_downloaded"
    assert client.post("/embedding/rebuild").status_code == 409
    assert client.get(f"/documents/{doc_id}").json()["embed_status"] == "pending"


@pytest.mark.slow
async def test_real_local_model_ranks_semantically(tmp_path):
    """需要网络：下载真实模型（约 135 MB）。pytest -m slow 运行。"""
    embedder = LocalEmbedder(MODELS["multilingual-e5-small"], tmp_path)
    async with httpx.AsyncClient(timeout=120) as client:
        await embedder.download(client, "https://huggingface.co")
    q = np.array(embedder.embed(["用了什么数据集"], "query"))
    p = np.array(
        embedder.embed(
            ["We evaluate classification accuracy on the ImageNet dataset.", "The sky is blue."]
        )
    )
    sims = q @ p.T
    assert sims[0, 0] > sims[0, 1]
