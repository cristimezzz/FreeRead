"""单篇问答：答案引用校验、上下文组装、QAService（含问答树）、重新解析后的引用迁移、API。"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from freeread.domain.qa.citations import strip_markers, validate_answer
from freeread.domain.qa.context import ContextBlock, build_context
from freeread.infra.db.models import LLMCallRow, QANodeRow
from freeread.infra.llm.fake import FakeProvider, qa_responder
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.search.chunker import approx_tokens
from freeread.services.llm_preflight import PreflightError
from freeread.services.qa import migrate_qa
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig

SYNTHETIC = Path(__file__).parent / "fixtures" / "raw" / "synthetic.pdf"


def configure(ctx, provider, *, consent=True, route=TaskKind.TRANSLATE):
    ctx.settings.put(
        AppSettings(
            providers=[ProviderConfig(id="p1", name="P1", base_url="http://p1.invalid/v1")],
            routes={route: ModelRoute(provider_id="p1", model="m1")},
            consented_providers=["p1"] if consent else [],
        )
    )
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
    return doc_id


async def collect(gen):
    return [e async for e in gen]


# ---------------------------------------------------------------- 纯函数


def test_validate_answer_normalizes_in_place_and_drops_unknown_ids():
    existing = {"b_0012", "b_0013", "b_0014"}
    v = validate_answer(
        "结论一 [b_12]。结论二【b_0013, b_9999】，以及 (d_ab12#b_14)。编造的 [b_77]。",
        existing,
        context_ids={"b_0012"},
    )
    assert v.text == "结论一[b_0012]。结论二[b_0013]，以及[b_0014]。编造的。"
    assert v.citations == ["b_0012", "b_0013", "b_0014"]
    assert v.invalid_ids == 2 and v.out_of_context == 2
    none = validate_answer("论文中没有找到相关内容。", existing)
    assert none.citations == [] and none.invalid_ids == 0
    assert strip_markers("结论 [b_0012][b_0013]。") == "结论。"


def CB(i, type_="paragraph", section="s1", text="word " * 20):
    return ContextBlock(f"b_{i:04d}", type_, section, text)


def test_build_context_neighbors_abstract_budget_and_order():
    blocks = [
        CB(0, "title", None, "A Paper"),
        CB(1, "abstract", None, "abstract " * 10),
        CB(2, "heading", "s1", "1 Intro"),
        CB(3),
        CB(4),
        CB(5),
        CB(6, section="s2"),  # 另一章：不是 b_0005 的邻块
        CB(7, section="s2", text=""),  # 不可用（装饰块等）
    ]
    titles = {"s1": "1 Intro", "s2": "2 Method"}
    ctx = build_context(["b_0005", "b_0007"], blocks, titles, approx_tokens, budget=1000)
    assert ctx.block_ids == ["b_0001", "b_0004", "b_0005"]  # 摘要 + 命中 + 同章前邻块，阅读顺序
    assert "## 1 Intro" in ctx.text and "[b_0005] " in ctx.text and "b_0002" not in ctx.text

    tight = build_context(["b_0005", "b_0003"], blocks, titles, approx_tokens, budget=40)
    assert "b_0005" in tight.block_ids and tight.tokens <= 40

    fallback = build_context([], blocks, titles, approx_tokens, budget=60)
    assert fallback.block_ids[:2] == ["b_0000", "b_0001"]  # 没有命中：论文开头


# ---------------------------------------------------------------- 服务


async def test_ask_streams_validates_saves_and_threads_history(ctx, tmp_path):
    fake = FakeProvider("p1", responder=qa_responder)
    configure(ctx, fake)  # 只配了翻译：问答回退到它
    doc_id = await parsed_doc(ctx, tmp_path)
    session = ctx.qa.create_session(doc_id)

    events = await collect(ctx.qa.ask(session.id, "What does the benchmark measure?"))
    kinds = [k for k, _ in events]
    assert kinds[0] == "context" and kinds[-1] == "answer"
    assert "delta" in kinds and set(kinds[1:-1]) == {"delta"}
    context = events[0][1]
    assert context.block_ids and context.modes == ["fts"]

    first = events[-1][1]
    assert "b_9999" not in first.answer and first.stats["invalid_ids"] == 1
    assert first.citations and all(c in context.block_ids for c in first.citations)
    assert not first.untraced and first.parent_id is None and first.model == "p1/m1"
    raw = "".join(p.text for k, p in events if k == "delta")
    assert "[b_9999]" in raw  # 流式文本是未校验的原文

    events = await collect(ctx.qa.ask(session.id, "And the limitations?", parent_id=first.id))
    second = events[-1][1]
    assert second.parent_id == first.id
    prompt = fake.calls[-1][1][-1].content
    assert "此前这一支的对话" in prompt and "What does the benchmark measure?" in prompt
    assert (
        "[b_" not in prompt.split("此前这一支的对话")[1].split("检索到的原文")[0]
    )  # 历史去掉了标记

    detail = ctx.qa.get_session(session.id)
    assert detail.title == "What does the benchmark measure?" and detail.turns == 2
    assert [n.id for n in detail.nodes] == [first.id, second.id]
    assert ctx.qa.list_sessions(doc_id)[0].turns == 2
    with ctx.sessions() as s:
        calls = s.scalars(select(LLMCallRow).where(LLMCallRow.task_kind == "qa")).all()
        assert len(calls) == 2 and all(c.doc_id == doc_id for c in calls)

    assert ctx.qa.delete_session(session.id)
    with ctx.sessions() as s:
        assert s.scalars(select(QANodeRow)).all() == []  # 级联删除
    assert ctx.qa.list_sessions(doc_id) == []


async def test_tree_branches_see_only_their_ancestors(ctx, tmp_path):
    fake = FakeProvider("p1", responder=qa_responder)
    configure(ctx, fake)
    doc_id = await parsed_doc(ctx, tmp_path)
    session = ctx.qa.create_session(doc_id)

    async def ask(q, **kw):
        return (await collect(ctx.qa.ask(session.id, q, **kw)))[-1][1]

    def history():
        prompt = fake.calls[-1][1][-1].content
        return prompt.split("检索到的原文")[0]

    root = await ask("Root question about the benchmark?")
    a = await ask("Child A about accuracy?", parent_id=root.id)
    b = await ask("Child B about limitations?", parent_id=root.id)  # 另起：与 A 同级
    assert a.parent_id == b.parent_id == root.id
    assert "Root question" in history() and "Child A" not in history()  # 兄弟分支不可见

    await ask("Grandchild under A?", parent_id=a.id)
    assert "Root question" in history() and "Child A" in history() and "Child B" not in history()

    other = await ask("A brand new topic?")  # 新话题：新的根
    assert other.parent_id is None and "此前这一支的对话" not in history()

    # 就此追问：选中的文字存进节点、写进提示词
    spawned = await ask("这是什么意思？", parent_id=root.id, anchor="  第一点\n 见此处 ")
    assert spawned.anchor == {"text": "第一点 见此处"}
    assert "选中了这段文字并就此追问：「第一点 见此处」" in fake.calls[-1][1][-1].content

    # 重答：同一问题、同一父节点，不走缓存（否则会拿回同一个缓存结果、不调用模型）
    n_calls = len(fake.calls)
    again = await ask(a.question, parent_id=root.id, regenerate=True)
    assert len(fake.calls) == n_calls + 1 and again.parent_id == root.id and again.id != a.id

    # 不属于本对话的父节点
    elsewhere = ctx.qa.create_session(doc_id)
    with pytest.raises(PreflightError) as e:
        await collect(ctx.qa.ask(elsewhere.id, "Q?", parent_id=root.id))
    assert e.value.code == "bad_request"

    # 删除子树：A 与它的孙节点一起删掉，其余不动
    assert ctx.qa.delete_node(a.id) == 2
    left = {n.id for n in ctx.qa.get_session(session.id).nodes}
    assert a.id not in left and {root.id, b.id, other.id, spawned.id, again.id} == left
    assert ctx.qa.delete_node(a.id) == 0


async def test_unanswerable_and_preflight(ctx, tmp_path):
    fake = FakeProvider("p1", script=["论文中没有找到相关内容。"])
    configure(ctx, fake, consent=False, route=TaskKind.SUMMARIZE)
    doc_id = await parsed_doc(ctx, tmp_path)
    session = ctx.qa.create_session(doc_id)
    with pytest.raises(PreflightError) as e:
        await collect(ctx.qa.ask(session.id, "Q?"))
    assert e.value.code == "consent_required" and fake.calls == []

    configure(ctx, fake, route=TaskKind.SUMMARIZE)  # 问答回退到总结的路由
    node = (await collect(ctx.qa.ask(session.id, "Q?")))[-1][1]
    assert node.untraced and node.citations == []


async def test_reparse_migrates_answer_markers(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=qa_responder))
    doc_id = await parsed_doc(ctx, tmp_path)
    session = ctx.qa.create_session(doc_id)
    node = (await collect(ctx.qa.ask(session.id, "benchmark accuracy")))[-1][1]
    a, b = node.citations[0], node.citations[-1]

    with ctx.sessions.begin() as s:
        assert migrate_qa(s, doc_id, {a: "b_0100"}) == (1 if a != b else 0)
    after = ctx.qa.get_session(session.id).nodes[0]
    assert "[b_0100]" in after.answer and after.citations[0] == "b_0100"
    if a != b:
        assert f"[{b}]" not in after.answer and after.status == "stale"

    # 真实重新解析：块 ID 不变，引用保留
    node = (await collect(ctx.qa.ask(session.id, "benchmark", parent_id=node.id)))[-1][1]

    async def noop(*_):
        pass

    await ctx.parse.run(doc_id, "pymupdf", noop, force=True)
    last = ctx.qa.get_session(session.id).nodes[-1]
    assert last.citations == node.citations and last.status == "ok"


# ---------------------------------------------------------------- API


def sse_events(body: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_qa_api(client, tmp_path):
    ctx = client.app.state.ctx
    configure(ctx, FakeProvider("p1", responder=qa_responder))
    doc_id = client.portal.call(parsed_doc, ctx, tmp_path)

    assert client.get(f"/documents/{doc_id}/qa/sessions").json() == []
    r = client.post(f"/documents/{doc_id}/qa/sessions", json={})
    assert r.status_code == 201
    sid = r.json()["id"]

    r = client.post(f"/qa/sessions/{sid}/ask", json={"question": "What is measured?"})
    assert r.status_code == 200
    events = sse_events(r.text)
    names = [e for e, _ in events]
    assert names[0] == "context" and names[-2:] == ["answer", "done"]
    answer = events[-2][1]
    assert answer["citations"] and "b_9999" not in answer["answer"]

    detail = client.get(f"/qa/sessions/{sid}").json()
    assert detail["turns"] == 1 and detail["nodes"][0]["id"] == answer["id"]

    body = {"question": "Why?", "parent_id": answer["id"], "anchor": "第一点"}
    child = sse_events(client.post(f"/qa/sessions/{sid}/ask", json=body).text)[-2][1]
    assert child["parent_id"] == answer["id"] and child["anchor"] == {"text": "第一点"}
    bad = sse_events(
        client.post(f"/qa/sessions/{sid}/ask", json={"question": "q", "parent_id": "x"}).text
    )
    assert bad[0] == (
        "error",
        {"code": "bad_request", "message": bad[0][1]["message"], "provider_id": None},
    )
    assert client.delete(f"/qa/nodes/{answer['id']}").status_code == 204  # 连同子节点
    assert client.get(f"/qa/sessions/{sid}").json()["nodes"] == []
    assert client.delete(f"/qa/nodes/{answer['id']}").status_code == 404
    assert client.post(f"/qa/sessions/{sid}/ask", json={"question": ""}).status_code == 422
    assert client.post("/qa/sessions/nope/ask", json={"question": "q"}).status_code == 404
    assert client.get("/qa/sessions/nope").status_code == 404
    assert client.get("/documents/nope/qa/sessions").status_code == 404
    assert client.delete(f"/qa/sessions/{sid}").status_code == 204
    assert client.delete(f"/qa/sessions/{sid}").status_code == 404


def test_eval_answer_metrics_and_review():
    from freeread.eval.qa import answer_metrics, dump_review_markdown

    node = {
        "question": "Q",
        "answer": "论文中没有找到相关内容，相近的信息见 [b_0001]。",
        "citations": ["b_0001"],
        "stats": {"invalid_ids": 2, "out_of_context": 1},
    }
    m = answer_metrics(node, {"b_0001"})
    assert m == {
        "shown": 1,
        "shown_valid": 1,
        "raw_total": 3,
        "raw_invalid": 2,
        "cited": True,
        "out_of_context": 1,
        "says_no_answer": True,
    }
    md = dump_review_markdown("T", [("q1", node)], {"b_0001": "原文  一段"})
    assert "## q1：Q" in md and "`b_0001` 原文 一段" in md


async def test_document_without_text_fails_fast_without_calling_model(ctx, tmp_path):
    from sqlalchemy import update

    from freeread.infra.db.models import BlockRow

    fake = FakeProvider("p1", responder=qa_responder)
    configure(ctx, fake)
    doc_id = await parsed_doc(ctx, tmp_path)
    with ctx.sessions.begin() as s:  # 模拟扫描版：没有任何正文
        s.execute(update(BlockRow).where(BlockRow.doc_id == doc_id).values(text="", html=None))
    session = ctx.qa.create_session(doc_id)
    with pytest.raises(PreflightError) as e:
        await collect(ctx.qa.ask(session.id, "Q?"))
    assert e.value.code == "no_text" and fake.calls == []
