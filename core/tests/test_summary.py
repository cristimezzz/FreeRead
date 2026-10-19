"""M2 分层总结：分组、引用校验、JSON 提取、Map / Reduce 服务、重新解析后的引用迁移、API。"""

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from freeread.domain.summary.citations import clean_point, coverage_stats, normalize_ids
from freeread.domain.summary.decoration import DecorationCandidate, decoration_ids
from freeread.domain.summary.grouping import SourceBlock, group_blocks
from freeread.domain.summary.parse_json import extract_json
from freeread.infra.db.models import BlockRow, LLMCallRow, SummaryRow
from freeread.infra.llm.errors import ProviderError
from freeread.infra.llm.fake import FakeProvider, summary_responder
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.search.chunker import approx_tokens
from freeread.services.doc_blocks import LoadedDoc, load_doc
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig
from freeread.services.summary import SummaryError, _source_blocks, migrate_summaries

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


PAGE = (600.0, 800.0)
TOP = (50.0, 20.0, 550.0, 40.0)  # 上边缘带（高 10% = 80pt 以内）
BOTTOM = (50.0, 770.0, 550.0, 790.0)
SIDE = (5.0, 200.0, 30.0, 600.0)  # 左侧竖排水印
BODY = (50.0, 300.0, 550.0, 400.0)


def DC(i, text, page=0, bbox=BODY, type_="paragraph"):
    return DecorationCandidate(f"b_{i:04d}", type_, text, [(page, bbox)])


def test_decoration_running_headers_repeat_at_page_edges():
    pages = {p: PAGE for p in range(4)}
    blocks = [
        DC(0, "Three-Color Live-Cell Imaging", 1, TOP),
        DC(1, "Three-Color  Live-Cell Imaging", 2, TOP),  # 空白不同也算同一行
        DC(2, "420 Current Anthropology Volume 55", 1, BOTTOM),
        DC(3, "422 Current Anthropology Volume 55", 3, BOTTOM),  # 页码不同也算同一行
        DC(4, "BIOPHYSICS AND", 2, SIDE),
        DC(5, "BIOPHYSICS AND", 3, SIDE),
        DC(6, "Only once at the top of a page", 1, TOP),  # 只出现一次：不动
        DC(7, "Repeated sentence in the body", 1),  # 重复但不在边缘：不动
        DC(8, "Repeated sentence in the body", 2),
    ]
    assert decoration_ids(blocks, pages) == {f"b_{i:04d}" for i in range(6)}


def test_decoration_boilerplate_lines():
    pages = {0: PAGE}
    drop = [
        "16121880, 2023, 2, Downloaded from https://onlinelibrary.wiley.com/doi/10.1002/x by Y",
        "npg © 2014 Nature America, Inc. All rights reserved.",
        (
            "Grubert et al., 2015, Cell 162, 1051–1065 August 27, 2015 ª2015 Elsevier Inc. "
            "http://dx.doi.org/10.1016/j.cell.2015.07.048"
        ),
        "Copyright © 2023 The Authors, some rights reserved; exclusive licensee AAAS.",
        "The Journal of Nutrition, Health & Aging© Volume 18, Number 2, 2014",
        "(legend continued on next page)",
    ]
    keep = [
        "We thank the authors of Waszak et al., 2015 for sharing data.",
        "Code is available at https://github.com/x/y.",  # 正文里的短 URL 句：不在边缘带
        "The volume of the cell increased 2-fold, see the next page for details.",
        "x" * 500 + " All rights reserved",  # 长块不按样板判断
    ]
    blocks = [DC(i, t) for i, t in enumerate(drop + keep)]
    assert decoration_ids(blocks, pages) == {f"b_{i:04d}" for i in range(len(drop))}

    # 边缘带里去掉 DOI 后几乎不剩字：装饰；剩下一句中文正文：不动
    edge = [
        DC(0, "doi:10.1038/nrg.2016.45 Published online 9 May 2016", 0, BOTTOM),
        DC(1, "doi.org/10.1002/cbdv.202201221 RESEARCH ARTICLE", 0, TOP),
        DC(2, "（https://doi.org/10.5281/zenodo.7839739），并可免费用于学术和研究用", 0, TOP),
        DC(3, "Code is available at https://github.com/x/y.", 0, BODY),
    ]
    assert decoration_ids(edge, pages) == {"b_0000", "b_0001"}


def test_decoration_never_touches_titles_captions_or_unanchored_blocks():
    pages = {p: PAGE for p in range(3)}
    blocks = [
        DC(0, "A Paper Title", 0, TOP, "title"),
        DC(1, "Figure 1. Copyright © 2020 shows the header", 0, BOTTOM, "caption"),
        DC(2, "Running title", 1, TOP, "heading"),
        DC(3, "Running title", 2, TOP, "heading"),
        DC(4, "First page abstract all rights reserved", 0, TOP, "abstract"),
        DecorationCandidate("b_0005", "paragraph", "Running", []),  # 没有锚点：只看样板
        DecorationCandidate("b_0006", "paragraph", "Running", [(9, TOP)]),  # 页码越界
    ]
    assert decoration_ids(blocks, pages) == set()


def test_source_blocks_blank_decorations_for_map():
    def row(i, text, page, bbox, type_="paragraph"):
        return BlockRow(
            doc_id="d", block_id=f"b_{i:04d}", ord=i, type=type_, section_id="s1", text=text,
            inlines=[], anchors=[{"page": page, "bbox": list(bbox)}], content_hash="h",
        )  # fmt: skip

    doc = LoadedDoc(
        "d",
        "en",
        [
            row(0, "A Paper", 0, TOP, "title"),
            row(1, "Downloaded from https://www.science.org at X on May 1, 2026", 0, SIDE),
            row(2, "Real body text about the experiment.", 0, BODY),
            row(3, "Downloaded from https://www.science.org at X on May 1, 2026", 1, SIDE),
        ],
        SECTIONS,
        {0: PAGE, 1: PAGE},
    )
    out = _source_blocks(doc)
    assert [b.text for b in out] == ["A Paper", "", "Real body text about the experiment.", ""]
    groups = group_blocks(out, SECTIONS, approx_tokens)
    assert [b for g in groups for b in g.block_ids] == ["b_0000", "b_0002"]


# ---------------------------------------------------------------- 服务


async def test_generate_map_reduce_saves_and_reuses_map_cache(ctx, tmp_path):
    fake = FakeProvider("p1", responder=summary_responder)
    configure(ctx, fake)  # 只配了翻译路由：总结回退到它
    doc_id = await parsed_doc(ctx, tmp_path)
    assert load_doc(ctx.sessions, ctx.paths, doc_id).pages[0][1] > 0  # 页面尺寸来自 ir.json

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


async def test_llm_opts_pass_through_and_concurrency_setting(ctx, tmp_path):
    fake = FakeProvider("p1", responder=summary_responder)
    configure(ctx, fake)
    doc_id = await parsed_doc(ctx, tmp_path)
    ctx.summary.set_concurrency(8)
    ctx.summary.llm_opts = {"thinking": {"type": "disabled"}}
    await collect(ctx.summary.generate(doc_id, "brief"))
    assert fake.calls and all(c[2] == {"thinking": {"type": "disabled"}} for c in fake.calls)


# 评测集 d_2ca951d5e87040a4 的真实回复形状：每个小节结尾都多写了下一个小节的 key（"…],"key_points"}"），
# 整体不是合法 JSON。此前兜底取到了要点对象，把它的 block_ids 当成小节，编号成了要点正文。
STRAY = (
    '{"sections":[{"key":"tldr","points":[{"text":"一句话","block_ids":["b_0003"]}],"key_points"},'
    '{"key":"key_points","points":[{"text":"要点","block_ids":["b_0005"]}],"limitations"},'
    '{"key":"limitations","points":[{"text":"局限","block_ids":["b_0007"]}]}]}'
)
# 修不了的坏回复：第一个小节缺了右括号
BROKEN = (
    '{"sections":[{"key":"tldr","points":[{"text":"一句话","block_ids":["b_0003"]}],'
    '{"key":"key_points","points":[{"text":"要点","block_ids":["b_0005"]}]},'
    '{"key":"limitations","points":[{"text":"局限","block_ids":["b_0007"]}]}]}'
)
GOOD = '{"sections":[{"key":"tldr","points":[{"text":"重试后的一句话","block_ids":["b_0003"]}]}]}'


def test_extract_json_repairs_dangling_keys_only_when_needed():
    data = extract_json(STRAY, "sections")
    assert [s["key"] for s in data["sections"]] == ["tldr", "key_points", "limitations"]
    # 结尾缺右括号（评测集 d_2d8e7b5188a46ca6）：补齐；括号交错的不修
    assert extract_json('{"sections":[{"key":"a","points":[{"text":"t"}]}', "sections")
    with pytest.raises(ValueError):
        extract_json('{"sections":[{"key":"a"]', "sections")
    valid = '{"text": "a,\\"b\\"}", "ids": ["x", "y"]}'
    assert extract_json(valid) == {"text": 'a,"b"}', "ids": ["x", "y"]}


def reduce_with(*replies):
    it = iter(replies)
    last = replies[-1]

    def responder(model, messages):
        if '"sections"' in messages[0].content:
            return next(it, last)
        return summary_responder(model, messages)

    return FakeProvider("p1", responder=responder)


async def test_reduce_repair_retry_and_salvage(ctx, tmp_path):
    configure(ctx, reduce_with(STRAY))
    doc_id = await parsed_doc(ctx, tmp_path)
    out = (await collect(ctx.summary.generate(doc_id, "brief")))[-1][1]
    assert [len(s.points) for s in out.sections] == [1, 1, 1]  # 修复后一次成功
    assert "salvaged" not in out.stats

    # 修不了：不走缓存重试，用重试的完整结果
    configure(ctx, reduce_with(BROKEN, GOOD))
    out = (await collect(ctx.summary.generate(doc_id, "brief", lang="en")))[-1][1]
    assert out.sections[0].points[0].text == "重试后的一句话"
    assert "salvaged" not in out.stats

    # 两次都修不了：拼回完整的小节对象；绝不出现以编号为正文的要点
    configure(ctx, reduce_with(BROKEN))
    out = (await collect(ctx.summary.generate(doc_id, "brief", lang="ja")))[-1][1]
    texts = [p.text for s in out.sections for p in s.points]
    assert out.stats["salvaged"] is True
    assert "要点" in texts and "局限" in texts
    assert not any(t.startswith("b_") for t in texts)
