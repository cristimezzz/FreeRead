"""M2：在评测集上跑分层总结，统计引用覆盖率（验收 ≥ 90%）与引用有效率。

用法（在 core/ 下）：
    # 真实模型（OpenAI 兼容接口），Key 从环境变量读取
    set FREEREAD_EVAL_API_KEY=sk-...
    .venv/Scripts/python ../scripts/m2_summary_eval.py --base-url https://api.deepseek.com/v1 --model deepseek-chat
    # 只验证链路（确定性假模型，不联网）
    .venv/Scripts/python ../scripts/m2_summary_eval.py --fake --limit 3

PDF 来自 core/tests/fixtures/pdfs/files/（不入库，见 manifest.yaml）。在进程内建一个独立数据目录
（默认 eval-out/m2-summary/data），导入、快速解析（PyMuPDF）后逐篇生成总结。输出：
- eval-out/m2-summary/<doc_id>.json：总结与统计；
- eval-out/m2-summary/<doc_id>.md：要点与引用原文对照稿，供人工抽检忠实度；
- eval-out/m2-summary/report.md：汇总表。
--record / --replay 把模型回复录下 / 回放（infra/llm/fake.py），便于在不花钱的情况下重跑。

耗时主要在模型生成。--jobs N 同时总结 N 篇（默认 4）；服务商限流时调小。推理模型（会先"思考"）
可以用 --extra-body 关掉思考，参数名因服务商而异，例如 '{"thinking": {"type": "disabled"}}'。
相同输入的调用会命中数据目录里的缓存，中断后重跑只补没完成的部分。
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import yaml

from freeread.context import AppContext
from freeread.eval.summary import citation_coverage, citation_validity, dump_review_markdown
from freeread.infra.llm.fake import FakeProvider, RecordingProvider, summary_responder
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.llm.secrets import SecretStore
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "core" / "tests" / "fixtures" / "pdfs"
OUT = ROOT / "eval-out" / "m2-summary"
TARGET = 0.9


async def noop(*_):
    pass


def configure(ctx: AppContext, args) -> None:
    settings = AppSettings(
        target_lang=args.lang,
        providers=[ProviderConfig(id="eval", name="评测", base_url=args.base_url)],
        routes={TaskKind.SUMMARIZE: ModelRoute(provider_id="eval", model=args.model)},
    )
    # 先保存服务地址再记同意：地址变了时 SettingsService 会作废旧的同意（隐私规则），
    # 同一次 put 里带上同意会被当成"旧地址的同意"丢掉
    ctx.settings.put(settings)
    ctx.settings.put(settings.model_copy(update={"consented_providers": ["eval"]}))
    if args.fake or args.replay:
        replay = Path(args.replay) if args.replay else None
        fake = FakeProvider("eval", responder=summary_responder, replay_file=replay)
        ctx.llm._factory = lambda config, key: fake
    elif args.record:
        default = ctx.llm._factory
        ctx.llm._factory = lambda config, key: RecordingProvider(
            default(config, key), Path(args.record)
        )


async def run_doc(ctx: AppContext, entry: dict, args) -> dict:
    pdf = FIX / "files" / f"{entry['doc_id']}.pdf"
    row = {"doc_id": entry["doc_id"], "title": entry.get("title", "")}
    if not pdf.is_file():
        return row | {"error": "PDF 不存在（files/ 不入库，先运行 scripts/m0_build_eval_set.py）"}
    item_id, _ = ctx.library.import_file(pdf)
    doc_id = ctx.library.get_item(item_id).documents[0].doc_id
    if ctx.parse.get(doc_id).parse_status != "ready":
        await ctx.parse.run(doc_id, args.engine, noop)

    started = time.perf_counter()
    summary = None
    try:
        async for name, payload in ctx.summary.generate(doc_id, args.template, args.lang):
            if name == "summary":
                summary = payload
    except Exception as e:  # noqa: BLE001  单篇失败只记录，不中断整批
        return row | {"error": f"{type(e).__name__}: {e}"}
    elapsed = time.perf_counter() - started

    sections = [s.model_dump() for s in summary.sections]
    cited, points = citation_coverage(sections)
    valid, total_ids = citation_validity(sections, summary.stats.get("invalid_ids", 0))
    doc = ctx.summary.load(doc_id)
    block_text = {b.block_id: b.text or (b.html or "") for b in doc.blocks}
    (OUT / f"{entry['doc_id']}.json").write_text(summary.model_dump_json(indent=2), "utf-8")
    (OUT / f"{entry['doc_id']}.md").write_text(
        dump_review_markdown(row["title"], sections, block_text), "utf-8"
    )
    return row | {
        "points": points,
        "cited": cited,
        "valid_ids": valid,
        "total_ids": total_ids,
        "groups": summary.stats.get("groups"),
        "failed_groups": summary.stats.get("failed_groups"),
        "seconds": round(elapsed, 1),
    }


def report(rows: list[dict], args) -> str:
    ok = [r for r in rows if "points" in r]
    points = sum(r["points"] for r in ok)
    cited = sum(r["cited"] for r in ok)
    ids = sum(r["total_ids"] for r in ok)
    valid = sum(r["valid_ids"] for r in ok)
    coverage = cited / points if points else 0.0
    model = "假模型（--fake）" if args.fake else args.model
    lines = [
        "# M2 总结评测",
        "",
        f"- 模型：{model}；模板：{args.template}；语言：{args.lang}；解析：{args.engine}",
        f"- 文档：{len(ok)} / {len(rows)} 篇成功",
        (
            f"- **引用覆盖率：{coverage:.1%}**（{cited} / {points} 个要点；"
            f"验收 ≥ {TARGET:.0%}：{'✅' if coverage >= TARGET else '❌'}）"
        ),
        f"- 引用有效率：{valid / ids:.1%}（{valid} / {ids}）" if ids else "- 引用有效率：—",
        "",
        "| doc_id | 标题 | 要点 | 覆盖率 | 有效引用 | 章节组（失败） | 耗时 s |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['doc_id']} | {r['title'][:40]} | ❌ {r['error']} | | | | |")
            continue
        cov = r["cited"] / r["points"] if r["points"] else 0
        lines.append(
            f"| {r['doc_id']} | {r['title'][:40]} | {r['points']} | {cov:.0%} | "
            f"{r['valid_ids']} / {r['total_ids']} | {r['groups']}（{r['failed_groups']}） | "
            f"{r['seconds']} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--data-dir", type=Path, default=OUT / "data")
    ap.add_argument("--docs", nargs="*", help="只跑这些 doc_id（默认 manifest 全部）")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--template", default="paper")
    ap.add_argument("--lang", default="zh-CN")
    ap.add_argument("--engine", default="pymupdf")
    ap.add_argument("--base-url", default="http://127.0.0.1:1/v1")
    ap.add_argument("--model", default="fake")
    ap.add_argument("--api-key-env", default="FREEREAD_EVAL_API_KEY")
    ap.add_argument("--fake", action="store_true", help="确定性假模型，只验证链路")
    ap.add_argument("--record", help="把真实模型的回复录进这个 JSON 文件")
    ap.add_argument("--replay", help="从 --record 录下的文件回放，不联网")
    ap.add_argument("--jobs", type=int, default=4, help="同时总结几篇（默认 4）")
    ap.add_argument(
        "--map-concurrency",
        type=int,
        help="所有文档合计同时进行的章节调用数（默认 jobs × 3，与应用里单篇的并发一致）",
    )
    ap.add_argument(
        "--extra-body",
        type=json.loads,
        default={},
        help='透传给服务商的请求参数（JSON），如关闭推理模型的思考：{"thinking": {"type": "disabled"}}',
    )
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env)
    if not (args.fake or args.replay or key):
        print(
            f"缺少 API Key：设置环境变量 {args.api_key_env}，或用 --fake 只验证链路",
            file=sys.stderr,
        )
        return 2

    manifest = yaml.safe_load((FIX / "manifest.yaml").read_text(encoding="utf-8"))
    entries = manifest["documents"]
    if args.docs:
        entries = [e for e in entries if e["doc_id"] in set(args.docs)]
    entries = entries[: args.limit] if args.limit else entries

    OUT.mkdir(parents=True, exist_ok=True)
    ctx = AppContext.open(args.data_dir, secrets=SecretStore({"eval": key or "sk-fake"}))
    try:
        configure(ctx, args)
        # 瓶颈在模型生成（推理模型每次 Map 10–20 s、Reduce 30–50 s），解析很快：
        # 多篇并行，并把总结服务的全局 Map 并发放大到 jobs × 3，免得各篇互相排队
        ctx.summary.set_concurrency(args.map_concurrency or args.jobs * 3)
        ctx.summary.llm_opts = args.extra_body
        jobs = asyncio.Semaphore(max(1, args.jobs))
        done = 0
        started = time.perf_counter()

        async def one(entry: dict) -> dict:
            nonlocal done
            async with jobs:
                row = await run_doc(ctx, entry, args)
            done += 1
            status = row.get("error") or (
                f"{row['cited']}/{row['points']} 个要点有引用，{row['seconds']} s"
            )
            print(f"[{done}/{len(entries)}] {entry['doc_id']} {status}", flush=True)
            return row

        rows = await asyncio.gather(*(one(e) for e in entries))
        print(f"总耗时 {time.perf_counter() - started:.0f} s（--jobs {args.jobs}）", flush=True)
        text = report(rows, args)
        (OUT / "report.md").write_text(text, encoding="utf-8")
        print(text)
    finally:
        await ctx.llm.aclose()
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
