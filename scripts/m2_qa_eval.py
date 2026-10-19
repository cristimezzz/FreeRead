"""M2：在评测集上跑单篇问答，检查答案引用（验收：展示的引用 100% 指向存在的块）。

用法（在 core/ 下）：
    # 真实模型（OpenAI 兼容接口），Key 从环境变量读取
    set FREEREAD_EVAL_API_KEY=sk-...
    .venv/Scripts/python ../scripts/m2_qa_eval.py --base-url https://api.deepseek.com/v1 --model deepseek-chat
    # 只验证链路（确定性假模型，不联网；输出到 eval-out/m2-qa-fake）
    .venv/Scripts/python ../scripts/m2_qa_eval.py --fake --limit 3

问题来自 core/tests/fixtures/pdfs/qa_questions.yaml：通用问题每篇都问，另有按 doc_id 追加的问题。
每个问题开一个新对话（互不影响）。输出：
- eval-out/m2-qa/<doc_id>.md：问题、回答与引用原文对照稿，供人工抽检忠实度；
- eval-out/m2-qa/report.md：汇总表。
--jobs / --record / --replay / --extra-body 同 m2_summary_eval.py。
"""

import argparse
import asyncio
import sys
import time

import yaml

from freeread.context import AppContext
from freeread.eval.qa import answer_metrics, dump_review_markdown
from freeread.eval.runner import (
    FIX,
    MISSING_PDF,
    ROOT,
    add_common_args,
    api_key,
    configure,
    import_and_parse,
    manifest_entries,
    resolve_dirs,
)
from freeread.infra.llm.fake import qa_responder
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.llm.secrets import SecretStore

OUT = ROOT / "eval-out" / "m2-qa"
QUESTIONS = FIX / "qa_questions.yaml"


def questions_for(spec: dict, doc_id: str) -> list[dict]:
    return list(spec.get("generic") or []) + list((spec.get("docs") or {}).get(doc_id) or [])


async def run_doc(ctx: AppContext, entry: dict, questions: list[dict], args) -> dict:
    row = {"doc_id": entry["doc_id"], "title": entry.get("title", "")}
    doc_id = await import_and_parse(ctx, entry, args.engine)
    if doc_id is None:
        return row | {"error": MISSING_PDF}
    doc = ctx.qa.load(doc_id)
    existing = {b.block_id for b in doc.blocks}
    block_text = {b.block_id: b.text or (b.html or "") for b in doc.blocks}

    started = time.perf_counter()
    turns, metrics, errors = [], [], []
    for q in questions:
        session = ctx.qa.create_session(doc_id, f"[eval] {q['id']}")
        try:
            node = None
            async for name, payload in ctx.qa.ask(session.id, q["text"], args.lang):
                if name == "answer":
                    node = payload.model_dump()
        except Exception as e:  # noqa: BLE001  单题失败只记录，不中断整批
            errors.append(f"{q['id']}: {type(e).__name__}: {e}")
            continue
        turns.append((q["id"], node))
        metrics.append(answer_metrics(node, existing) | {"expect": q.get("expect")})
    (args.out / f"{entry['doc_id']}.md").write_text(
        dump_review_markdown(row["title"], turns, block_text), "utf-8"
    )
    normal = [m for m in metrics if m["expect"] != "no_answer"]
    traps = [m for m in metrics if m["expect"] == "no_answer"]
    return row | {
        "answered": len(metrics),
        "asked": len(questions),
        "shown": sum(m["shown"] for m in metrics),
        "shown_valid": sum(m["shown_valid"] for m in metrics),
        "raw_total": sum(m["raw_total"] for m in metrics),
        "raw_invalid": sum(m["raw_invalid"] for m in metrics),
        "cited": sum(m["cited"] for m in normal),
        "normal": len(normal),
        "out_of_context": sum(m["out_of_context"] for m in metrics),
        "traps": len(traps),
        "traps_ok": sum(1 for m in traps if not m["cited"] or m["says_no_answer"]),
        "errors": errors,
        "seconds": round(time.perf_counter() - started, 1),
    }


def report(rows: list[dict], args, elapsed: float) -> str:
    ok = [r for r in rows if "answered" in r]

    def total(key: str) -> int:
        return sum(r[key] for r in ok)

    def pct(a: int, b: int) -> str:
        return f"{a / b:.1%}（{a} / {b}）" if b else "—"

    shown, valid = total("shown"), total("shown_valid")
    model = "假模型（--fake）" if args.fake else args.model
    lines = [
        "# M2 问答评测",
        "",
        f"- 模型：{model}；语言：{args.lang}；解析：{args.engine}",
        (
            f"- 文档：{len(ok)} / {len(rows)} 篇；回答 {total('answered')} / {total('asked')} 题；"
            f"总耗时 {elapsed:.0f} s（--jobs {args.jobs}）"
        ),
        (
            f"- **展示引用有效率：{pct(valid, shown)}**"
            f"（验收 100%：{'✅' if shown and valid == shown else '❌'}）"
        ),
        (
            f"- 模型原始编号有效率：{pct(total('raw_total') - total('raw_invalid'), total('raw_total'))}"
            "（无效的已在校验时删除）"
        ),
        f"- 有引用的回答（不含陷阱题）：{pct(total('cited'), total('normal'))}",
        f"- 引用不在所给上下文里：{pct(total('out_of_context'), shown)}",
        f"- 陷阱题没有编造（不给引用或说明没找到）：{pct(total('traps_ok'), total('traps'))}",
        "",
        "| doc_id | 标题 | 回答 | 展示引用有效 | 原始无效编号 | 有引用的回答 | 陷阱题 | 耗时 s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['doc_id']} | {r['title'][:40]} | ❌ {r['error']} | | | | | |")
            continue
        lines.append(
            f"| {r['doc_id']} | {r['title'][:40]} | {r['answered']} / {r['asked']} | "
            f"{r['shown_valid']} / {r['shown']} | {r['raw_invalid']} | "
            f"{r['cited']} / {r['normal']} | {r['traps_ok']} / {r['traps']} | {r['seconds']} |"
        )
    errors = [e for r in ok for e in r["errors"]]
    if errors:
        lines += ["", "## 失败的问题", "", *[f"- {e}" for e in errors]]
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_common_args(ap, OUT)
    args = ap.parse_args()
    key = api_key(args)
    if key is None:
        return 2
    entries = manifest_entries(args)
    resolve_dirs(args, OUT)
    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))

    ctx = AppContext.open(args.data_dir, secrets=SecretStore({"eval": key}))
    try:
        configure(ctx, args, TaskKind.QA, qa_responder)
        ctx.qa.llm_opts = args.extra_body
        jobs = asyncio.Semaphore(max(1, args.jobs))
        done = 0
        started = time.perf_counter()

        async def one(entry: dict) -> dict:
            nonlocal done
            async with jobs:
                row = await run_doc(ctx, entry, questions_for(spec, entry["doc_id"]), args)
            done += 1
            status = row.get("error") or (
                f"{row['answered']}/{row['asked']} 题，展示引用 {row['shown_valid']}/{row['shown']} 有效，"
                f"{row['seconds']} s"
            )
            print(f"[{done}/{len(entries)}] {entry['doc_id']} {status}", flush=True)
            return row

        rows = await asyncio.gather(*(one(e) for e in entries))
        elapsed = time.perf_counter() - started
        text = report(rows, args, elapsed)
        (args.out / "report.md").write_text(text, encoding="utf-8")
        print(text)
    finally:
        await ctx.llm.aclose()
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
