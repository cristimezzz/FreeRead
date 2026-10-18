import asyncio
import json
import shutil
from pathlib import Path

import pytest

from freeread.infra.db.models import BlockRow, LLMCallRow, TranslationRow
from freeread.infra.llm.errors import RetryableError
from freeread.infra.llm.fake import FakeProvider
from freeread.infra.llm.gateway import LLMResult, TaskKind, Usage
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig
from freeread.services.translate import TranslateError

SYNTHETIC = Path(__file__).parent / "fixtures" / "raw" / "synthetic.pdf"
MARK = "待翻译段落：\n"


def zh(model, messages):
    """假翻译：把待翻译段落原样加上前缀，占位符保持不变。"""
    user = messages[-1].content
    return "译：" + user.split(MARK, 1)[1].strip()


def configure(ctx, provider, consent=True, key=True):
    ctx.settings.put(
        AppSettings(
            providers=[ProviderConfig(id="p1", name="P1", base_url="http://p1.invalid/v1")],
            routes={TaskKind.TRANSLATE: ModelRoute(provider_id="p1", model="m1")},
            consented_providers=["p1"] if consent else [],
        )
    )
    if key:
        ctx.secrets.set("p1", "sk-test-123")
    ctx.llm._factory = lambda config, k: provider

    async def no_sleep(_s):
        pass

    ctx.llm._sleep = no_sleep


async def parsed_doc(ctx, tmp_path):
    src = tmp_path / "paper.pdf"
    shutil.copyfile(SYNTHETIC, src)
    item_id, _ = ctx.library.import_file(src)
    doc_id = ctx.library.get_item(item_id).documents[0].doc_id

    async def noop(*_):
        pass

    await ctx.parse.run(doc_id, "pymupdf", noop)
    with ctx.sessions() as s:
        blocks = {
            r.type: r.block_id
            for r in reversed(
                s.query(BlockRow).filter_by(doc_id=doc_id).order_by(BlockRow.ord).all()
            )
        }
        ordered = [
            (r.block_id, r.type, r.text)
            for r in s.query(BlockRow).filter_by(doc_id=doc_id).order_by(BlockRow.ord)
        ]
    return doc_id, blocks, ordered


async def collect(gen):
    return [e async for e in gen]


async def test_translates_saves_and_serves_from_cache(ctx, tmp_path):
    fake = FakeProvider("p1", responder=zh)
    configure(ctx, fake)
    doc_id, first, ordered = await parsed_doc(ctx, tmp_path)
    para = [b for b, t, _ in ordered if t == "paragraph"][:3]
    ref = first["reference_entry"]

    events = await collect(ctx.translate.translate_blocks(doc_id, [*para, ref, "b_9999"]))
    by_id = {e.block_id: e for e in events}
    assert set(by_id) == {*para, ref}  # 不存在的块被忽略
    assert by_id[ref].status == "skipped"
    assert all(by_id[b].status == "ok" and by_id[b].text.startswith("译：") for b in para)
    assert len(fake.calls) == 3

    saved = ctx.translate.list_for_doc(doc_id, "zh-CN")
    assert {t.block_id for t in saved} == set(para)
    assert saved[0].model == "p1/m1" and saved[0].prompt_version == "translate@1"

    again = await collect(ctx.translate.translate_blocks(doc_id, para))
    assert [e.cached for e in again] == [True, True, True]
    assert [e.block_id for e in again] == para  # 已有译文按请求顺序返回
    assert len(fake.calls) == 3


async def test_prompt_context_has_title_section_and_previous_paragraph(ctx, tmp_path):
    fake = FakeProvider("p1", responder=zh)
    configure(ctx, fake)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    paras = [i for i, (_, t, _) in enumerate(ordered) if t == "paragraph"]
    # 找一个前一块也是段落的段落
    i = next(i for i in paras if i - 1 in paras)
    await collect(ctx.translate.translate_blocks(doc_id, [ordered[i][0]]))
    user = fake.calls[0][1][-1].content
    assert "A Synthetic Study of Layout Parsing" in user
    assert ordered[i - 1][2][:40] in user
    assert "简体中文" in fake.calls[0][1][0].content


async def test_placeholder_mismatch_retries_without_cache_then_needs_review(ctx, tmp_path):
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    block_id, _, text = next(o for o in ordered if o[1] == "paragraph")
    with ctx.sessions.begin() as s:  # 给这一块加一个引用，让译文必须保留 ⟦CITE1⟧
        s.get(BlockRow, (doc_id, block_id)).text = text + " [7]"

    fake = FakeProvider("p1", script=["丢了引用", "译文 ⟦CITE1⟧"])
    configure(ctx, fake)
    [event] = await collect(ctx.translate.translate_blocks(doc_id, [block_id]))
    assert (event.status, event.text) == ("ok", "译文 [7]")
    assert len(fake.calls) == 2

    other_id = [o for o in ordered if o[1] == "paragraph"][1][0]
    fake2 = FakeProvider("p1", script=["坏 ⟦CITE9⟧", "还是坏 ⟦EQ5⟧"])
    configure(ctx, fake2)
    [event] = await collect(ctx.translate.translate_blocks(doc_id, [other_id]))
    assert event.status == "needs_review"
    assert event.text == next(o for o in ordered if o[0] == other_id)[2]  # 回退原文
    saved = {t.block_id: t.status for t in ctx.translate.list_for_doc(doc_id, "zh-CN")}
    assert saved == {block_id: "ok", other_id: "needs_review"}


async def test_preflight_errors_come_after_cached_translations(ctx, tmp_path):
    fake = FakeProvider("p1", responder=zh)
    configure(ctx, fake)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    paras = [b for b, t, _ in ordered if t == "paragraph"]
    await collect(ctx.translate.translate_blocks(doc_id, paras[:1]))

    configure(ctx, fake, consent=False)
    gen = ctx.translate.translate_blocks(doc_id, paras[:2])
    first = await anext(gen)
    assert first.cached and first.block_id == paras[0]
    with pytest.raises(TranslateError) as e:
        await anext(gen)
    assert e.value.code == "consent_required" and e.value.provider_id == "p1"

    ctx.secrets.delete("p1")
    configure(ctx, fake, key=False)
    with pytest.raises(TranslateError, match="API Key") as e:
        await collect(ctx.translate.translate_blocks(doc_id, paras[1:2]))
    assert e.value.code == "missing_api_key"

    ctx.settings.put(AppSettings())
    with pytest.raises(TranslateError) as e:
        await collect(ctx.translate.translate_blocks(doc_id, paras[1:2]))
    assert e.value.code == "route_not_configured"


async def test_offline_errors_per_block_and_keeps_existing(ctx, tmp_path):
    ok = FakeProvider("p1", responder=zh)
    configure(ctx, ok)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    paras = [b for b, t, _ in ordered if t == "paragraph"]
    await collect(ctx.translate.translate_blocks(doc_id, paras[:1]))

    down = FakeProvider("p1", script=[RetryableError("connect failed")] * 3)
    configure(ctx, down)
    events = await collect(ctx.translate.translate_blocks(doc_id, paras[:2]))
    assert events[0].cached and events[0].status == "ok"
    assert events[1].status == "error" and "connect failed" in events[1].message
    assert len(down.calls) == 3  # Gateway 重试了 3 次
    with ctx.sessions() as s:
        assert s.query(TranslationRow).count() == 1


async def test_same_language_documents_are_skipped(ctx, tmp_path):
    fake = FakeProvider("p1", responder=zh)
    configure(ctx, fake)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    paras = [b for b, t, _ in ordered if t == "paragraph"]
    events = await collect(ctx.translate.translate_blocks(doc_id, paras[:2], lang="en"))
    assert {e.status for e in events} == {"skipped"} and fake.calls == []


class GatedProvider:
    """complete 卡在 gate 上，用来制造并发与取消。"""

    name = "p1"

    def __init__(self):
        self.gate = asyncio.Event()
        self.started = 0

    async def complete(self, model, messages, **opts):
        self.started += 1
        await self.gate.wait()
        return LLMResult(zh(model, messages), model, Usage(1, 1))


async def test_concurrent_requests_share_one_call_and_disconnect_cancels(ctx, tmp_path):
    gated = GatedProvider()
    configure(ctx, gated)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    paras = [b for b, t, _ in ordered if t == "paragraph"]

    a = asyncio.create_task(collect(ctx.translate.translate_blocks(doc_id, paras[:1])))
    b = asyncio.create_task(collect(ctx.translate.translate_blocks(doc_id, paras[:1])))
    while gated.started < 1:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    gated.gate.set()
    ea, eb = await asyncio.gather(a, b)
    assert gated.started == 1 and ea[0].text == eb[0].text

    gated.gate.clear()
    gen = ctx.translate.translate_blocks(doc_id, paras[1:2])
    pending = asyncio.ensure_future(anext(gen))
    while gated.started < 2:
        await asyncio.sleep(0.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await gen.aclose()
    await asyncio.sleep(0.05)
    assert ctx.translate._inflight == {} and not ctx.translate._waiters
    assert [t.block_id for t in ctx.translate.list_for_doc(doc_id, "zh-CN")] == paras[:1]


async def test_retranslation_switches_active_row_and_records_usage(ctx, tmp_path):
    fake = FakeProvider("p1", responder=zh)
    configure(ctx, fake)
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    block_id = next(b for b, t, _ in ordered if t == "paragraph")
    await collect(ctx.translate.translate_blocks(doc_id, [block_id]))
    ctx.translate._save(doc_id, block_id, "zh-CN", "p1/m2", "translate@1", "新译文", "ok")
    [t] = ctx.translate.list_for_doc(doc_id, "zh-CN")
    assert (t.model, t.text) == ("p1/m2", "新译文")
    with ctx.sessions() as s:
        assert s.query(TranslationRow).filter_by(is_active=False).count() == 1
        call = s.query(LLMCallRow).one()
        assert call.task_kind == "translate" and call.doc_id == doc_id


def sse_events(body: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_translate_api_streams_sse(client, tmp_path):
    ctx = client.app.state.ctx
    fake = FakeProvider("p1", responder=zh)
    configure(ctx, fake)
    doc_id, _, ordered = client.portal.call(parsed_doc, ctx, tmp_path)
    paras = [b for b, t, _ in ordered if t == "paragraph"][:2]

    resp = client.post("/translate/blocks", json={"doc_id": doc_id, "block_ids": paras})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = sse_events(resp.text)
    assert [e for e, _ in events] == ["translation", "translation", "done"]
    assert {d["block_id"] for _, d in events[:2]} == set(paras)

    listed = client.get(f"/documents/{doc_id}/translations").json()
    assert {t["block_id"] for t in listed} == set(paras)

    configure(ctx, fake, consent=False)
    more = [b for b, t, _ in ordered if t == "paragraph"][2:3]
    events = sse_events(
        client.post("/translate/blocks", json={"doc_id": doc_id, "block_ids": more}).text
    )
    assert events[0] == (
        "error",
        {
            "code": "consent_required",
            "message": "向 P1 发送文档内容前需要确认",
            "provider_id": "p1",
        },
    )
    assert events[-1][0] == "done"

    assert (
        client.post(
            "/translate/blocks", json={"doc_id": "d_0000000000000000", "block_ids": ["b_0000"]}
        ).status_code
        == 404
    )
    assert client.get("/documents/d_0000000000000000/translations").status_code == 404
