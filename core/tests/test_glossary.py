import json

import pytest

from freeread.infra.db.models import LLMCallRow, TranslationRow
from freeread.infra.jobs.queue import JobStatus
from freeread.infra.jobs.worker import JobContext
from freeread.infra.llm.fake import FakeProvider
from freeread.infra.llm.gateway import TaskKind
from freeread.services.glossary import GlossaryConflict, TermIn, TermPatch, _matcher
from freeread.services.llm_preflight import PreflightError
from tests.test_translate import MARK, configure, parsed_doc

TERMS_REPLY = json.dumps(
    {
        "terms": [
            {"source": "Lorem", "target": "洛雷姆", "note": ""},
            {"source": "ipsum", "target": "伊普苏姆"},
            {"source": "", "target": "空"},  # 丢弃
            "bad",  # 丢弃
        ]
    },
    ensure_ascii=False,
)


def responder(model, messages):
    """抽取任务回 JSON；翻译回原文加前缀，并把注入的术语表抄在最前面，便于断言。"""
    user = messages[-1].content
    if MARK not in user:
        return "好的，结果如下：\n```json\n" + TERMS_REPLY + "\n```"
    glossary = user.split("术语表：", 1)[1].split("\n\n")[0] if "术语表：" in user else ""
    return f"[{glossary.strip()}]译：" + user.split(MARK, 1)[1].strip()


async def run_job(ctx, kind: str, handler) -> None:
    job = ctx.jobs.claim_next({kind})
    assert job is not None
    await handler(JobContext(job, ctx.jobs))
    ctx.jobs.finish(job.id, JobStatus.DONE)


def test_matcher_word_boundaries_and_cjk():
    m = _matcher("codon")
    assert m.search("Codons are optimized")
    assert m.search("the codon.")
    assert not m.search("anticodonal")
    assert _matcher("mRNA vaccine").search("mRNA  vaccines work")
    assert _matcher("密码子").search("优化密码子使用")
    assert _matcher("β-barrel").search("the FhuA β-barrel")


def test_crud_scopes_and_override(ctx):
    g = ctx.glossary
    glob = g.create(TermIn(source="Transformer", target="变换器"))
    assert glob.scope == "global" and glob.origin == "user" and glob.lang == "zh-CN"
    with pytest.raises(GlossaryConflict):
        g.create(TermIn(source="  transformer ", target="x"))

    # 文档条目需要真实文档（外键）；这里只测全局条目的增改删和匹配
    hits = g.terms_for_block("d_x", "zh-CN", "A transformer model")
    assert hits == [{"source": "Transformer", "target": "变换器"}]

    changed = g.update(glob.id, TermPatch(target="Transformer"))
    assert changed.target == "Transformer"
    assert g.terms_for_block("d_x", "zh-CN", "transformers")[0]["target"] == "Transformer"
    assert g.terms_for_block("d_x", "en", "transformers") == []  # 按目标语言区分

    assert g.delete(glob.id) and not g.delete(glob.id)
    assert g.terms_for_block("d_x", "zh-CN", "A transformer model") == []


async def test_extract_job_keeps_user_terms(ctx, tmp_path):
    fake = FakeProvider("p1", responder=responder)
    configure(ctx, fake)
    doc_id, _, _ = await parsed_doc(ctx, tmp_path)
    g = ctx.glossary
    g.create(TermIn(source="lorem", target="用户译法", doc_id=doc_id))

    job = g.request_extract(doc_id)
    assert g.request_extract(doc_id).id == job.id  # 去重
    await run_job(ctx, "glossary_extract", g.run_extract_job)

    terms = {t.source: t for t in g.list_terms(doc_id=doc_id)}
    assert terms["lorem"].target == "用户译法" and terms["lorem"].origin == "user"
    assert terms["ipsum"].origin == "auto" and terms["ipsum"].scope == f"doc:{doc_id}"
    assert "Lorem" not in terms and "" not in terms
    assert g.has_auto_terms(doc_id)
    with ctx.sessions() as s:
        call = s.query(LLMCallRow).filter_by(prompt_id="glossary_extract@1").one()
        assert call.task_kind == TaskKind.GLOSSARY

    # 重新抽取只替换 auto 条目；改过的 auto 条目变成 user，不再被替换
    g.update(terms["ipsum"].id, TermPatch(note="改过"))
    g.request_extract(doc_id)
    await run_job(ctx, "glossary_extract", g.run_extract_job)
    after = {t.source: t for t in g.list_terms(doc_id=doc_id)}
    assert after["ipsum"].origin == "user" and after["ipsum"].note == "改过"
    assert len(after) == 2

    # 提升为全局：文档外也生效
    g.update(after["ipsum"].id, TermPatch(scope="global"))
    assert [t.scope for t in g.list_terms()] == ["global"]


async def test_translation_injects_hit_terms(ctx, tmp_path):
    fake = FakeProvider("p1", responder=responder)
    configure(ctx, fake)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    para_id, _, text = next(b for b in ordered if b[1] == "paragraph")
    word = text.split()[1].strip(".,;:")
    ctx.glossary.create(TermIn(source=word, target="术语译法", doc_id=doc_id))
    ctx.glossary.create(TermIn(source="zzzunused", target="不出现"))

    [event] = [e async for e in ctx.translate.translate_blocks(doc_id, [para_id])]
    assert event.status == "ok"
    assert event.text.startswith(f"[- {word} → 术语译法]译：")
    assert "不出现" not in event.text

    # 改了术语后，同一段落不再命中旧缓存
    with ctx.sessions.begin() as s:
        s.query(TranslationRow).delete()
    term = ctx.glossary.list_terms(doc_id=doc_id)[0]
    ctx.glossary.update(term.id, TermPatch(target="新译法"))
    [event] = [e async for e in ctx.translate.translate_blocks(doc_id, [para_id])]
    assert "新译法" in event.text and not event.cached


async def test_translate_doc_job(ctx, tmp_path):
    fake = FakeProvider("p1", responder=responder)
    configure(ctx, fake)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    paras = [b for b, t, _ in ordered if t == "paragraph"]
    # 先在阅读器里翻了一段：整篇翻译跳过它
    _ = [e async for e in ctx.translate.translate_blocks(doc_id, paras[:1])]
    calls_before = len(fake.calls)

    job = ctx.translate.request_doc(doc_id)
    assert ctx.translate.request_doc(doc_id).id == job.id
    assert job.depends_on is None  # 默认不自动抽取
    await run_job(ctx, "translate_doc", ctx.translate.run_doc_job)

    done = ctx.jobs.get(job.id)
    assert done.message.startswith("翻译 ")
    translated = {t.block_id for t in ctx.translate.list_for_doc(doc_id, "zh-CN")}
    assert set(paras) <= translated
    assert len(fake.calls) - calls_before == len(translated) - 1


async def test_translate_doc_auto_extract_dependency(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=responder))
    settings = ctx.settings.get()
    ctx.settings.put(
        settings.model_copy(
            update={"glossary": settings.glossary.model_copy(update={"auto_extract": True})}
        )
    )
    doc_id, _, _ = await parsed_doc(ctx, tmp_path)
    job = ctx.translate.request_doc(doc_id)
    dep = ctx.jobs.get(job.depends_on)
    assert dep.kind == "glossary_extract" and dep.payload["doc_id"] == doc_id


async def test_preflight_errors(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=responder), consent=False)
    doc_id, _, _ = await parsed_doc(ctx, tmp_path)
    with pytest.raises(PreflightError) as e:
        ctx.translate.request_doc(doc_id)
    assert e.value.code == "consent_required"
    with pytest.raises(PreflightError):
        ctx.glossary.request_extract(doc_id)
    assert ctx.jobs.list() == [] or all(j.kind == "parse" for j in ctx.jobs.list())


def test_glossary_api(client, tmp_path):
    ctx = client.app.state.ctx
    configure(ctx, FakeProvider("p1", responder=responder))
    doc_id, _, _ = client.portal.call(parsed_doc, ctx, tmp_path)

    r = client.post("/glossary", json={"source": "Encoder", "target": "编码器"})
    assert r.status_code == 201
    term = r.json()
    assert client.post("/glossary", json={"source": "encoder", "target": "x"}).status_code == 409
    r = client.post("/glossary", json={"source": "Decoder", "target": "解码器", "doc_id": doc_id})
    assert r.status_code == 201 and r.json()["scope"] == f"doc:{doc_id}"
    assert (
        client.post("/glossary", json={"source": "a", "target": "b", "doc_id": "nope"}).status_code
        == 404
    )

    assert [t["source"] for t in client.get("/glossary").json()] == ["Encoder"]
    listed = client.get("/glossary", params={"doc_id": doc_id}).json()
    assert [t["source"] for t in listed] == ["Decoder", "Encoder"]

    r = client.patch(f"/glossary/{term['id']}", json={"target": "编码器（改）"})
    assert r.status_code == 200 and r.json()["target"] == "编码器（改）"
    assert client.patch("/glossary/nope", json={"target": "x"}).status_code == 404
    assert client.delete(f"/glossary/{term['id']}").status_code == 204
    assert client.delete(f"/glossary/{term['id']}").status_code == 404

    r = client.post(f"/documents/{doc_id}/glossary/extract", json={})
    assert r.status_code == 202 and r.json()["kind"] == "glossary_extract"
    r = client.post(f"/documents/{doc_id}/translate", json={})
    assert r.status_code == 202 and r.json()["kind"] == "translate_doc"
    assert client.post("/documents/nope/translate", json={}).status_code == 404

    ctx.settings.put(ctx.settings.get().model_copy(update={"consented_providers": []}))
    r = client.post(f"/documents/{doc_id}/glossary/extract", json={"lang": "en"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_required"
    r = client.post(f"/documents/{doc_id}/translate", json={"lang": "ja"})
    assert r.status_code == 409 and r.json()["detail"]["provider_id"] == "p1"
