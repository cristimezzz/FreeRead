"""M3：在评测集上跑知识图谱抽取（每篇一张图），输出统计和人工抽检稿。

用法（在 core/ 下）：
    # 真实模型（OpenAI 兼容接口），Key 从环境变量读取
    set FREEREAD_EVAL_API_KEY=sk-...
    .venv/Scripts/python ../scripts/m3_kg_eval.py --base-url https://api.deepseek.com/v1 --model deepseek-chat
    # 只验证链路（确定性假模型，不联网；输出到 eval-out/m3-kg-fake）
    .venv/Scripts/python ../scripts/m3_kg_eval.py --fake --limit 3

每次运行先清空图谱（保留解析结果和模型回复缓存），统计只算本次运行的调用；警告（组失败、重试）写进 run.log。
输出：
- eval-out/m3-kg/<doc_id>.md：数值结果（achieves）与出处原文对照、其他关系与摘句、实体（按重要性），供人工抽检；
- eval-out/m3-kg/report.md：每篇实体 / 关系数、精简掉的实体数、丢弃统计。
--jobs / --record / --replay / --extra-body 同 m2_summary_eval.py。
"""

import argparse
import asyncio
import logging
import re
import sys
import time
from collections import Counter

from sqlalchemy import delete, update

from freeread.context import AppContext
from freeread.domain.kg.extract import MAX_ENTITIES, prune
from freeread.eval.runner import (
    MISSING_PDF,
    ROOT,
    add_common_args,
    api_key,
    configure,
    import_and_parse,
    manifest_entries,
    resolve_dirs,
)
from freeread.infra.db.base import utcnow
from freeread.infra.db.models import (
    BlockRow,
    DocumentRow,
    KGEntityRow,
    KGMentionRow,
    KGRelationRow,
    LLMCallRow,
)
from freeread.infra.llm.fake import kg_responder
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.llm.secrets import SecretStore
from freeread.infra.search.text import block_plain_text
from freeread.services import kg as kg_mod

OUT = ROOT / "eval-out" / "m3-kg"


class _Progress:
    async def report(self, *_args) -> None:
        pass


async def run_doc(ctx: AppContext, entry: dict, args, sem) -> dict:
    row = {"doc_id": entry["doc_id"], "title": entry.get("title", "")}
    async with sem:
        doc_id = await import_and_parse(ctx, entry, args.engine)
        if doc_id is None:
            return row | {"error": MISSING_PDF}
        prompt = ctx.prompts.get(kg_mod.PROMPT_ID)
        started = time.perf_counter()
        try:
            graph = prune(await ctx.kg._extract(doc_id, prompt, _Progress()))
        except Exception as e:  # noqa: BLE001  单篇失败只记录，不中断整批
            return row | {"error": f"{type(e).__name__}: {e}"}
        await asyncio.to_thread(ctx.kg._store, doc_id, graph, f"eval/{args.model}+{prompt.ref}")
    stats = graph.stats
    types = Counter(e.type.value for e in graph.entities)
    rels = Counter(r.type.value for r in graph.relations)
    return row | {
        "doc": doc_id,
        "entities": len(graph.entities),
        "relations": len(graph.relations),
        "achieves": rels["achieves"],
        "types": types,
        "rel_types": rels,
        "pruned": stats["pruned"],
        "failed_groups": stats["failed_groups"],
        "dropped_values": stats["unverified_values"],
        "no_source": stats["no_source"],
        "bad_relations": stats["bad_relations"],
        "bad_entities": stats["bad_entities"],
        "unsupported_evidence": stats["unsupported_evidence"],
        "seconds": round(time.perf_counter() - started, 1),
    }


def review_markdown(ctx: AppContext, doc_id: str, title: str) -> str:
    g = ctx.kg.doc_graph(doc_id)
    with ctx.sessions() as s:
        blocks = {
            b.block_id: block_plain_text(b.type, b.text, b.inlines, b.html)
            for b in s.query(BlockRow).filter_by(doc_id=doc_id)
        }
    lines = [f"# {title}", "", f"{len(g.entities)} 个实体、{len(g.relations)} 条关系", ""]
    results = [r for r in g.relations if r.type == "achieves"]
    lines += [f"## 数值结果（{len(results)}）", ""]
    for r in results:
        a = r.attrs
        extra = "，".join(f"{k}={a[k]}" for k in ("dataset", "unit", "setting") if k in a)
        lines += [
            (
                f"- **{r.src_name}** · {a.get('metric', r.dst_name)} = {a.get('value_text')}"
                f"{'（' + extra + '）' if extra else ''} [{r.block_id}] conf={r.confidence}"
            ),
            f"  > {blocks.get(r.block_id, '')[:400]}",
        ]
    others = [r for r in g.relations if r.type != "achieves"]
    lines += ["", f"## 其他关系（{len(others)}）", ""]
    for r in others:
        lines.append(
            f"- {r.src_name} —{r.type}→ {r.dst_name} [{r.block_id}] conf={r.confidence}"
            + (f"：“{r.evidence}”" if r.evidence else "")
        )
    lines += ["", "## 实体（按重要性）", ""]
    for e in g.entities:
        alias = f"（{'、'.join(e.aliases)}）" if e.aliases else ""
        lines.append(f"- [{e.type}] {e.name}{alias} · {e.score}")
    return "\n".join(lines) + "\n"


class _Collect(logging.Handler):
    """收集本次运行的警告（组失败、重试），写进报告；完整内容另存 run.log。"""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


_KIND_RE = re.compile(
    r"HTTP \d+[^{]*\{.*?\"message\":\"([^\"(]{1,60})|HTTP \d+|\b\w+(?:Error|Timeout)\b"
)


def _warning_kind(message: str) -> str:
    """警告归类：HTTP 状态码 + 服务商给的说明，或异常类名；都没有时取开头一段。"""
    m = _KIND_RE.search(message)
    if not m:
        return message[:60]
    status = re.search(r"HTTP \d+", m.group(0))
    # 服务商的说明里可能带账户 / 密钥标识（DeepSeek 的 429："… for api_key: <id>"），不写进报告
    detail = re.split(r"\s+for\s+api_?key", m.group(1) or "", flags=re.IGNORECASE)[0].strip()
    return " ".join(x for x in ((status.group(0) if status else m.group(0)), detail) if x)


def reset_graph(ctx: AppContext) -> None:
    """清空上一次运行留下的图谱（保留解析结果和模型回复缓存），让每次运行都从空库开始。"""
    with ctx.sessions.begin() as s:
        for row in (KGRelationRow, KGMentionRow, KGEntityRow):
            s.execute(delete(row))
        s.execute(update(DocumentRow).values(kg_status="pending"))


def report(
    ctx: AppContext,
    rows: list[dict],
    args,
    elapsed: float,
    run_started: str,
    warnings: list[logging.LogRecord],
) -> str:
    ok = [r for r in rows if "entities" in r]

    def total(key: str) -> int:
        return sum(r[key] for r in ok)

    with ctx.sessions() as s:
        n_entities = s.query(KGEntityRow).count()
        n_relations = s.query(KGRelationRow).count()
        calls = (
            s.query(LLMCallRow)
            .filter(
                LLMCallRow.task_kind == TaskKind.KG_EXTRACT.value,
                LLMCallRow.created_at >= run_started,
            )
            .all()
        )
        # 检查：每条关系的出处块都存在
        block_ids = {(b.doc_id, b.block_id) for b in s.query(BlockRow.doc_id, BlockRow.block_id)}
        rel_rows = s.query(KGRelationRow).all()
        valid = sum((r.doc_id, r.source_block_id) in block_ids for r in rel_rows)
    in_tok = sum(c.input_tokens for c in calls)
    out_tok = sum(c.output_tokens for c in calls)
    model = "假模型（--fake）" if args.fake else args.model
    types = sum((r["types"] for r in ok), Counter())
    rel_types = sum((r["rel_types"] for r in ok), Counter())
    lines = [
        "# M3 图谱抽取评测",
        "",
        f"- 模型：{model}；解析：{args.engine}",
        f"- 文档：{len(ok)} / {len(rows)} 篇；总耗时 {elapsed:.0f} s（--jobs {args.jobs}，组并发 {kg_mod.CONCURRENCY}）",
        f"- 调用 {len(calls)} 次（缓存命中 {sum(c.cache_hit for c in calls)}），输入 {in_tok} / 输出 {out_tok} token",
        (
            f"- 合计：{n_entities} 个实体（每篇最多 {MAX_ENTITIES}，精简掉 {total('pruned')} 个）、"
            f"{n_relations} 条关系；**出处块存在 {valid} / {len(rel_rows)}**"
        ),
        f"- 实体类型：{dict(types.most_common())}",
        f"- 关系类型：{dict(rel_types.most_common())}",
        (
            f"- 丢弃：数值核对不上 {total('dropped_values')}、出处不在本组 {total('no_source')}、"
            f"关系不合法 {total('bad_relations')}、实体不合法或无出处 {total('bad_entities')}；"
            f"摘句核对不上（已清空）{total('unsupported_evidence')}；失败的组 {total('failed_groups')}"
        ),
        "",
        "| doc_id | 标题 | 实体 | 关系 | 数值结果 | 精简 | 丢弃数值 | 失败组 | 耗时 s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(
                f"| {r['doc_id']} | {r['title'][:40]} | ❌ {r['error'][:80]} | | | | | | |"
            )
            continue
        lines.append(
            f"| {r['doc_id']} | {r['title'][:40]} | {r['entities']} | {r['relations']} | "
            f"{r['achieves']} | {r['pruned']} | {r['dropped_values']} | {r['failed_groups']} | "
            f"{r['seconds']} |"
        )
    if warnings:
        kinds = Counter(_warning_kind(r.getMessage()) for r in warnings)
        lines += ["", f"## 警告（{len(warnings)} 条，全文见 run.log）", ""]
        lines += [f"- {n} × {k}" for k, n in kinds.most_common(20)]
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    add_common_args(ap, OUT)
    ap.add_argument("--group-jobs", type=int, default=3, help="一篇内同时调用的组数（默认 3）")
    args = ap.parse_args()
    resolve_dirs(args, OUT)
    key = api_key(args)
    if key is None:
        return 2

    collect = _Collect()
    log_file = logging.FileHandler(args.out / "run.log", mode="w", encoding="utf-8")
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[log_file, collect])

    kg_mod.CONCURRENCY = args.group_jobs
    ctx = AppContext.open(args.data_dir, secrets=SecretStore({"eval": key}))
    configure(ctx, args, TaskKind.KG_EXTRACT, kg_responder)
    if args.extra_body:
        ctx.kg.llm_opts = args.extra_body
    reset_graph(ctx)

    entries = manifest_entries(args)
    sem = asyncio.Semaphore(args.jobs)
    run_started = utcnow()
    started = time.perf_counter()
    rows = await asyncio.gather(*(run_doc(ctx, e, args, sem) for e in entries))
    elapsed = time.perf_counter() - started
    for r in rows:
        if "doc" in r:
            (args.out / f"{r['doc_id']}.md").write_text(
                review_markdown(ctx, r["doc"], r["title"]), "utf-8"
            )
    text = report(ctx, list(rows), args, elapsed, run_started, collect.records)
    (args.out / "report.md").write_text(text, "utf-8")
    print(text)
    ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
