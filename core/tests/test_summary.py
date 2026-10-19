"""M2 分层总结：分组、引用校验、JSON 提取、Map / Reduce 服务、重新解析后的引用迁移、API。"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from freeread.domain.summary.citations import clean_point, coverage_stats, normalize_ids
from freeread.domain.summary.grouping import SourceBlock, group_blocks
from freeread.domain.summary.parse_json import extract_json
from freeread.infra.db.models import LLMCallRow, SummaryRow
from freeread.infra.llm.errors import ProviderError
from freeread.infra.llm.fake import FakeProvider, summary_responder
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.search.chunker import approx_tokens
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig
from freeread.services.summary import SummaryError, migrate_summaries

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


def SB(i, type_="paragraph", section="s1", text="word " * 10):
    return SourceBlock(f"b_{i:04d}", type_, section, text)


SECTIONS = [
    {"id": "s1", "title": "1 Introduction", "level": 1, "parent_id": None},
    {"id": "s2", "title": "2 Method", "level": 1, "parent_id": None},
    {"id": "s21", "title": "2.1 Model", "level": 2, "parent_id": "s2"},
    {"id": "s3", "title": "References", "level": 1, "parent_id": None},
]


def test_grouping_by_top_level_section_with_preamble_and_subsections():
    blocks = [
        SB(0, "title", None, "A Paper"),
        SB(1, "abstract", None),
        SB(2, "heading", "s1", "1 Introduction"),
        SB(3),
        SB(4, "heading", "s2", "2 Method"),
        SB(5, section="s2"),
        SB(6, "heading", "s21", "2.1 Model"),
        SB(7, section="s21"),
        SB(8, "reference_entry", "s3", ""),  # 不可检索类型展开后为空
    ]
    groups = group_blocks(blocks, SECTIONS, approx_tokens, target=10, max_tokens=1000)
    assert [g.block_ids for g in groups] == [["b_0000", "b_0001"], ["b_0003"], ["b_0005", "b_0007"]]
    assert groups[0].title == "标题与摘要"
    assert groups[2].title == "2 Method"
    assert "[b_0007] " in groups[2].content and "## 2.1 Model" in groups[2].content
    assert "b_0004" not in groups[2].content  # 标题块不带编号


def test_grouping_merges_small_and_splits_large():
    small = [SB(i, section=f"s{i}") for i in range(1, 4)]
    secs = [{"id": f"s{i}", "title": f"S{i}", "level": 1, "parent_id": None} for i in range(1, 4)]
    merged = group_blocks(small, secs, approx_tokens, target=1000)
    assert len(merged) == 1 and merged[0].block_ids == ["b_0001", "b_0002", "b_0003"]
    assert merged[0].title == "S1、S2、S3"

    big = [SB(i, text="word " * 400) for i in range(10)]
    split = group_blocks(big, SECTIONS, approx_tokens, target=300, max_tokens=600)
    assert len(split) > 1
    assert sum(len(g.block_ids) for g in split) == 10
    assert all(g.tokens <= 600 for g in split)
    assert split[1].title.endswith("（续）")


def test_citation_normalization_and_validation():
    assert normalize_ids(["b_12", "B_0012", "d_ab12#b_0013", "b-7"]) == [
        "b_0012",
        "b_0013",
        "b_0007",
    ]
    assert normalize_ids("b_1, b_2") == ["b_0001", "b_0002"]
    existing = {"b_0001", "b_0002"}
    point, bad = clean_point({"text": "结论 [b_0002]", "block_ids": ["b_1", "b_9999"]}, existing)
    assert point == {"text": "结论", "block_ids": ["b_0001", "b_0002"]} and bad == 1
    point, bad = clean_point({"text": "无据可查", "block_ids": []}, existing)
    assert point["untraced"] and bad == 0
    assert clean_point({"text": "  "}, existing) == (None, 0)
    stats = coverage_stats([{"block_ids": ["b_0001"]}, {"block_ids": []}], 3)
    assert stats == {"points": 2, "cited_points": 1, "coverage": 0.5, "invalid_ids": 3}


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('好的：\n```json\n{"points": [{"text": "x}"}]}\n```\n以上') == {
        "points": [{"text": "x}"}]
    }
    with pytest.raises(ValueError):
        extract_json("no json here")


# ---------------------------------------------------------------- 服务


async def test_generate_map_reduce_saves_and_reuses_map_cache(ctx, tmp_path):
    fake = FakeProvider("p1", responder=summary_responder)
    configure(ctx, fake)  # 只配了翻译路由：总结回退到它
    doc_id = await parsed_doc(ctx, tmp_path)

    events = await collect(ctx.summary.generate(doc_id, "paper"))
    kinds = [k for k, _ in events]
    assert kinds[0] == "progress" and kinds[-1] == "summary"
    maps = [p for k, p in events if k == "progress" and p.stage == "map"]
    n_groups = maps[0].total
    assert [p.done for p in maps] == list(range(n_groups + 1))
    assert len(fake.calls) == n_groups + 1  # Map 每组一次 + Reduce 一次

    out = events[-1][1]
    assert [s.key for s in out.sections] == [
        "problem", "method", "experiments", "conclusions", "limitations", "reusable",
    ]  # fmt: skip
    assert out.stats["coverage"] == 1.0 and out.stats["invalid_ids"] == 0
    assert out.model == "p1/m1"
    assert out.prompt_version == "summarize_map@1+summarize_reduce@1+paper@1"
    assert ctx.summary.list_for_doc(doc_id, "zh-CN")[0].id == out.id
    with ctx.sessions() as s:
        calls = s.scalars(select(LLMCallRow).where(LLMCallRow.task_kind == "summarize")).all()
        assert len(calls) == n_groups + 1 and all(c.doc_id == doc_id for c in calls)

    # 换模板：Map 全部命中缓存，只多一次 Reduce
    fake.calls.clear()
    events = await collect(ctx.summary.generate(doc_id, "brief"))
    assert len(fake.calls) == 1
    assert [s.key for s in events[-1][1].sections] == ["tldr", "key_points", "limitations"]

    # 同一模板重新生成：替换而不是新增
    await collect(ctx.summary.generate(doc_id, "paper"))
    assert len(ctx.summary.list_for_doc(doc_id)) == 2


async def test_preflight_errors(ctx, tmp_path):
    fake = FakeProvider("p1", responder=summary_responder)
    configure(ctx, fake, consent=False)
    doc_id = await parsed_doc(ctx, tmp_path)
    with pytest.raises(SummaryError) as e:
        await collect(ctx.summary.generate(doc_id, "nope"))
    assert e.value.code == "unknown_template"
    from freeread.services.llm_preflight import PreflightError

    with pytest.raises(PreflightError) as e:
        await collect(ctx.summary.generate(doc_id, "paper"))
    assert e.value.code == "consent_required" and e.value.provider_id == "p1"
    assert fake.calls == []


async def test_invalid_json_retries_once_and_bad_citations_are_flagged(ctx, tmp_path):
    def responder(model, messages):
        if '"sections"' in messages[0].content:
            return json.dumps(
                {
                    "sections": [
                        {"key": "研究问题", "points": [{"text": "有据", "block_ids": ["b_3"]}]},
                        {"key": "method", "points": [{"text": "编造", "block_ids": ["b_9999"]}]},
                    ]
                }
            )
        return summary_responder(model, messages)

    fake = FakeProvider("p1", script=["not json"], responder=responder)
    configure(ctx, fake)
    doc_id = await parsed_doc(ctx, tmp_path)
    events = await collect(ctx.summary.generate(doc_id, "paper"))
    out = events[-1][1]
    assert out.sections[0].points[0].block_ids == ["b_0003"]  # 小节名写在 key 里也能认出
    assert out.sections[1].points[0].untraced and out.sections[1].points[0].block_ids == []
    assert out.stats["coverage"] == 0.5 and out.stats["invalid_ids"] == 1
    # 第一次 Map 回复不是 JSON → 不走缓存重试了一次
    assert fake.calls[0][2] == {} and len(fake.calls) == out.stats["groups"] + 2


async def test_all_map_failures_raise_llm_error(ctx, tmp_path):
    fake = FakeProvider(
        "p1", responder=lambda m, msgs: (_ for _ in ()).throw(ProviderError("boom"))
    )
    configure(ctx, fake)
    doc_id = await parsed_doc(ctx, tmp_path)
    with pytest.raises(SummaryError) as e:
        await collect(ctx.summary.generate(doc_id, "brief"))
    assert e.value.code == "llm_error" and "boom" in str(e.value)


async def test_reparse_migrates_citations_and_marks_stale(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=summary_responder))
    doc_id = await parsed_doc(ctx, tmp_path)
    await collect(ctx.summary.generate(doc_id, "brief"))

    with ctx.sessions.begin() as s:
        assert migrate_summaries(s, doc_id, {"b_0003": "b_0030"}) == 1
    out = ctx.summary.list_for_doc(doc_id)[0]
    assert out.status == "stale"
    ids = [i for sec in out.sections for p in sec.points for i in p.block_ids]
    assert ids and set(ids) <= {"b_0030"}

    # 真实重新解析：块 ID 不变时引用全部保留
    await collect(ctx.summary.generate(doc_id, "brief"))

    async def noop(*_):
        pass

    await ctx.parse.run(doc_id, "pymupdf", noop, force=True)
    with ctx.sessions() as s:
        row = s.scalar(select(SummaryRow).where(SummaryRow.doc_id == doc_id))
        assert row.status == "ok" and row.stats["coverage"] == 1.0


# ---------------------------------------------------------------- API


def sse_events(body: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_summary_api(client, tmp_path):
    ctx = client.app.state.ctx
    configure(ctx, FakeProvider("p1", responder=summary_responder))
    doc_id = client.portal.call(parsed_doc, ctx, tmp_path)

    templates = client.get("/summary/templates").json()
    assert [t["id"] for t in templates] == ["paper", "brief"]
    assert client.get(f"/documents/{doc_id}/summaries").json() == []

    r = client.post(f"/documents/{doc_id}/summary", json={"template_id": "brief"})
    assert r.status_code == 200
    events = sse_events(r.text)
    assert [e for e, _ in events][-2:] == ["summary", "done"]
    assert events[-2][1]["sections"][0]["key"] == "tldr"

    listed = client.get(f"/documents/{doc_id}/summaries").json()
    assert len(listed) == 1 and listed[0]["stats"]["coverage"] == 1.0

    r = client.post(f"/documents/{doc_id}/summary", json={"template_id": "nope"})
    assert sse_events(r.text)[0] == (
        "error",
        {"code": "unknown_template", "message": "未知的总结模板 'nope'", "provider_id": None},
    )
    assert client.post("/documents/nope/summary", json={}).status_code == 404
    assert client.get("/documents/nope/summaries").status_code == 404


def test_eval_metrics_and_review_markdown():
    from freeread.eval.summary import citation_coverage, citation_validity, dump_review_markdown

    sections = [
        {"key": "a", "name": "A", "points": [{"text": "p1", "block_ids": ["b_0001"]}]},
        {"key": "b", "name": "B", "points": [{"text": "p2", "block_ids": [], "untraced": True}]},
    ]
    assert citation_coverage(sections) == (1, 2)
    assert citation_validity(sections, invalid_ids=1) == (1, 2)
    md = dump_review_markdown("T", sections, {"b_0001": "原文   一段"})
    assert "`b_0001` 原文 一段" in md and "p2 **（未溯源）**" in md


async def test_reduce_salvages_flattened_sections_and_rejects_empty(ctx, tmp_path):
    # 真实模型（评测集 d_be31326296626169）回过这种坏结构：其他小节写成第一个小节对象里的键，
    # 外层括号还不配对。此前取到内层对象后没有 sections，静默保存了空总结。
    broken = (
        '{"sections":[{"key":"tldr","points":[{"text":"一句话","block_ids":["b_0003"]}],'
        '"key_points":[{"text":"要点","block_ids":["b_0005"]}],'
        '"limitations":[{"text":"局限","block_ids":["b_0007"]}]}'
    )

    def responder(model, messages):
        if '"sections"' in messages[0].content:
            return broken
        return summary_responder(model, messages)

    configure(ctx, FakeProvider("p1", responder=responder))
    doc_id = await parsed_doc(ctx, tmp_path)
    out = (await collect(ctx.summary.generate(doc_id, "brief")))[-1][1]
    assert [[p.block_ids for p in s.points] for s in out.sections] == [
        [["b_0003"]],
        [["b_0005"]],
        [["b_0007"]],
    ]

    def empty(model, messages):
        if '"sections"' in messages[0].content:
            return '{"sections": [{"key": "tldr", "points": []}]}'
        return summary_responder(model, messages)

    fake = FakeProvider("p1", responder=empty)
    configure(ctx, fake)
    with pytest.raises(SummaryError) as e:
        await collect(ctx.summary.generate(doc_id, "paper"))
    assert e.value.code == "bad_output"
    reduce_calls = [c for c in fake.calls if '"sections"' in c[1][0].content]
    assert len(reduce_calls) == 2  # 不走缓存重试了一次
    assert [s.template_id for s in ctx.summary.list_for_doc(doc_id)] == ["brief"]  # 没存空总结
