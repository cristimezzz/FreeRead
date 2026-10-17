"""M0：汇总解析评测结果。

读取 eval-out/<engine>/<doc_id>/{run.json, ir.json} 与 core/tests/golden/<doc_id>.json，
输出 docs/m0/parser-eval-results.json（入库，只含数字）与 docs/m0/parser-eval-tables.md。

用法：core/.venv/Scripts/python scripts/m0_report.py
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

import yaml

from freeread.eval.metrics import PB, Scores, blocks_from_ir, score_document

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "core" / "tests" / "fixtures" / "pdfs"
GOLD = ROOT / "core" / "tests" / "golden"
OUT = ROOT / "eval-out"
DOCS = ROOT / "docs" / "m0"
ENGINES = ("pymupdf", "mineru", "docling")  # Marker 已移除，见报告
CATEGORIES = ("two_column", "formula", "table_heavy", "scanned", "chinese", "long_appendix")
CAT_ZH = {
    "all": "全部",
    "two_column": "双栏",
    "formula": "含公式",
    "table_heavy": "表格多",
    "scanned": "扫描版",
    "chinese": "中文",
    "long_appendix": "长附录",
}


def load_golden(doc_id: str) -> dict[int, list[PB]] | None:
    f = GOLD / f"{doc_id}.json"
    if not f.exists():
        return None
    g = json.loads(f.read_text(encoding="utf-8"))
    return {
        p["page"]: [
            PB(
                page=p["page"],
                bbox=tuple(b["bbox"]),
                type=b["type"],
                order=b["order"],
                text=b.get("text") or "",
                latex=b.get("latex"),
            )
            for b in p["blocks"]
        ]
        for p in g["pages"]
    }


def linfit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    return my - b * mx, b


def fmt(v, pct=False, nd=3):
    if v is None:
        return "–"
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def main() -> None:
    manifest = yaml.safe_load((FIX / "manifest.yaml").read_text(encoding="utf-8"))["documents"]
    tags = {d["doc_id"]: set(d["tags"]) for d in manifest}
    results: dict = {"engines": {}, "n_docs": len(manifest)}

    for e in ENGINES:
        runs = []
        for d in manifest:
            f = OUT / e / d["doc_id"] / "run.json"
            if f.exists():
                runs.append(json.loads(f.read_text(encoding="utf-8")))
        ok = [r for r in runs if r.get("ok")]
        by_cat: dict[str, Scores] = defaultdict(Scores)
        per_doc = {}
        for r in ok:
            gold = load_golden(r["doc_id"])
            if gold is None:
                continue
            ir = json.loads((OUT / e / r["doc_id"] / "ir.json").read_text(encoding="utf-8"))
            s = score_document(gold, blocks_from_ir(ir))
            per_doc[r["doc_id"]] = s.summary()
            by_cat["all"].merge(s)
            for c in CATEGORIES:
                if c in tags[r["doc_id"]]:
                    # merge 会原地累加，这里给每个类别单独算一份
                    by_cat[c].merge(score_document(gold, blocks_from_ir(ir)))
        full = [r for r in ok if not r.get("page_subset")]
        fit = linfit([r["pages"] for r in full], [r["wall_s"] for r in full])
        results["engines"][e] = {
            "runs": len(runs),
            "ok": len(ok),
            "failed": [
                {"doc_id": r["doc_id"], "error": r.get("error")} for r in runs if not r.get("ok")
            ],
            "pages_processed": sum(r["pages"] for r in ok),
            "partial_pages": any(r.get("page_subset") for r in ok),
            "s_per_page_mean": statistics.mean(r["s_per_page"] for r in ok) if ok else None,
            "s_per_page_median": statistics.median(r["s_per_page"] for r in ok) if ok else None,
            "total_wall_s": sum(r["wall_s"] for r in ok),
            "startup_s_fit": fit[0] if fit else None,
            "marginal_s_per_page_fit": fit[1] if fit else None,
            "peak_rss_mb_max": max((r["peak_rss_mb"] for r in ok), default=None),
            "peak_vram_mb_max": max((r["peak_vram_mb"] for r in ok), default=None),
            "peak_vram_mb_median": statistics.median(r["peak_vram_mb"] for r in ok) if ok else None,
            "ir_problems_total": sum(r.get("n_problems", 0) for r in ok),
            "docs_with_ir_problems": sum(1 for r in ok if r.get("n_problems")),
            "metrics": {c: s.summary() for c, s in by_cat.items()},
            "per_doc": per_doc,
        }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "parser-eval-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    E = results["engines"]
    lines = ["<!-- 由 scripts/m0_report.py 生成，请勿手改 -->", ""]
    lines += ["### 总体质量（golden 抽样页）", ""]
    lines += [
        "| 引擎 | 检测 F1 | 类型准确率 | 粗粒度类型准确率 | 阅读顺序 τ | 文本 NED↓ | 公式召回 | 公式 LaTeX NED↓ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in ENGINES:
        m = E[e]["metrics"].get("all")
        if not m:
            continue
        lines.append(
            f"| {e} | {fmt(m['det_f1'])} | {fmt(m['type_acc'], True)} | {fmt(m['coarse_type_acc'], True)} | "
            f"{fmt(m['reading_order_tau'])} | {fmt(m['text_ned'])} | {fmt(m['equation_recall'], True)} | {fmt(m['latex_ned'])} |"
        )
    lines += ["", "### 按类别：检测 F1 / 粗粒度类型准确率 / 阅读顺序 τ", ""]
    lines += ["| 类别 | " + " | ".join(ENGINES) + " |", "|---|" + "---|" * len(ENGINES)]
    for c in ("all", *CATEGORIES):
        cells = []
        for e in ENGINES:
            m = E[e]["metrics"].get(c)
            cells.append(
                f"{fmt(m['det_f1'], nd=2)} / {fmt(m['coarse_type_acc'], True)} / {fmt(m['reading_order_tau'], nd=2)}"
                if m
                else "–"
            )
        n = sum(1 for d in manifest if c == "all" or c in tags[d["doc_id"]])
        lines.append(f"| {CAT_ZH[c]}（{n} 篇） | " + " | ".join(cells) + " |")
    lines += ["", "### 各类型 F1（全部）", ""]
    types = sorted(
        {t for e in ENGINES for t in (E[e]["metrics"].get("all") or {}).get("per_type_f1", {})}
    )
    lines += ["| 类型 | " + " | ".join(ENGINES) + " |", "|---|" + "---|" * len(ENGINES)]
    for t in types:
        lines.append(
            f"| {t} | "
            + " | ".join(
                fmt((E[e]["metrics"].get("all") or {}).get("per_type_f1", {}).get(t), nd=2)
                for e in ENGINES
            )
            + " |"
        )
    lines += ["", "### 速度与资源（RTX 3050 Ti Laptop 4GB / Windows 11）", ""]
    lines += [
        "| 引擎 | 成功 / 运行 | 处理页数 | 秒/页（中位） | 启动开销（拟合） | 边际秒/页（拟合） | 峰值内存 | 峰值显存（中位 / 最大） | IR 校验问题 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for e in ENGINES:
        x = E[e]
        if not x["runs"]:
            continue
        lines.append(
            f"| {e} | {x['ok']} / {x['runs']} | {x['pages_processed']}{'（仅抽样页）' if x['partial_pages'] else ''} | "
            f"{fmt(x['s_per_page_median'], nd=2)} | {fmt(x['startup_s_fit'], nd=1)} s | {fmt(x['marginal_s_per_page_fit'], nd=2)} | "
            f"{fmt(x['peak_rss_mb_max'], nd=0)} MB | {fmt(x['peak_vram_mb_median'], nd=0)} / {fmt(x['peak_vram_mb_max'], nd=0)} MB | "
            f"{x['ir_problems_total']}（{x['docs_with_ir_problems']} 篇） |"
        )
    (DOCS / "parser-eval-tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
