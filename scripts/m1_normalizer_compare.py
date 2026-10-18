"""M1：对比两版 Normalizer 在 M0 golden 评测集上的指标（只换 Normalizer，不重跑引擎）。

用法：
    core/.venv/Scripts/python scripts/m1_normalizer_compare.py --before <eval-out 目录> --after <eval-out 目录>

两个目录的结构与 eval-out/ 相同（<engine>/<doc_id>/ir.json），通常由
`scripts/m0_run_parsers.py --renormalize` 分别在旧 / 新代码上生成。

除 m0_report.py 的全部指标外，另给出两个"同口径"对照，用来区分"指标变差"与"参与计算的块变了"：
- τ（同匹配块）：只在新旧两版都匹配上的 golden 块上计算阅读顺序 τ；
- 文本 NED（含 author_info）：golden 与预测的粗粒度类型都是文本类时就计入，
  不受 author_info 不在 metrics.TEXTUAL 中的影响。
"""

import argparse
import json
from pathlib import Path

import yaml
from m0_report import CATEGORIES, FIX, load_golden

from freeread.eval.metrics import (
    COARSE,
    Scores,
    blocks_from_ir,
    kendall_tau,
    match,
    ned,
    normalize_text,
    score_document,
)

ENGINES = ("pymupdf", "mineru", "docling")
KEYS = (
    ("det_f1", "检测 F1", False),
    ("type_acc", "类型准确率", True),
    ("coarse_type_acc", "粗粒度类型准确率", True),
    ("reading_order_tau", "阅读顺序 τ", False),
    ("text_ned", "文本 NED↓", False),
    ("equation_recall", "公式召回", True),
    ("latex_ned", "公式 LaTeX NED↓", False),
)
LOWER_BETTER = {"text_ned", "latex_ned"}
TEXT_COARSE = {"text", "heading", "caption", "reference"}


def load(root: Path, engine: str, doc_id: str):
    f = root / engine / doc_id / "ir.json"
    return blocks_from_ir(json.loads(f.read_text(encoding="utf-8"))) if f.exists() else None


def controls(gold, before, after) -> tuple[float, int, float, int, list[float], list[float]]:
    """返回 (τ_before·对数, 对数, τ_after·对数, 对数, NED_before 列表, NED_after 列表)。"""
    tb = ta = 0.0
    nb = na = 0
    ned_b: list[float] = []
    ned_a: list[float] = []
    for page, gb in gold.items():
        pb = [p for p in before if p.page == page]
        pa = [p for p in after if p.page == page]
        mb, ma = dict(match(gb, pb)), dict(match(gb, pa))
        common = sorted(set(mb) & set(ma), key=lambda i: gb[i].order)
        t, n = kendall_tau([pb[mb[i]].order for i in common])
        tb, nb = tb + t * n, nb + n
        t, n = kendall_tau([pa[ma[i]].order for i in common])
        ta, na = ta + t * n, na + n
        for m, pred, out in ((mb, pb, ned_b), (ma, pa, ned_a)):
            for i, j in m.items():
                g, p = gb[i], pred[j]
                if (
                    g.text
                    and COARSE.get(g.type) in TEXT_COARSE
                    and COARSE.get(p.type) in TEXT_COARSE
                ):
                    out.append(ned(normalize_text(g.text), normalize_text(p.text)))
    return tb, nb, ta, na, ned_b, ned_a


def fmt(v, pct: bool) -> str:
    if v is None:
        return "–"
    return f"{v * 100:.1f}%" if pct else f"{v:.4f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--json", type=Path, help="把全部数字另存为 JSON")
    a = ap.parse_args()

    manifest = yaml.safe_load((FIX / "manifest.yaml").read_text(encoding="utf-8"))["documents"]
    tags = {d["doc_id"]: set(d["tags"]) for d in manifest}
    out: dict = {}
    for e in ENGINES:
        sb: dict[str, Scores] = {}
        sa: dict[str, Scores] = {}
        ctl = [0.0, 0, 0.0, 0, [], []]
        for d in manifest:
            did = d["doc_id"]
            gold = load_golden(did)
            before, after = load(a.before, e, did), load(a.after, e, did)
            if gold is None or before is None or after is None:
                continue
            for c in ("all", *CATEGORIES):
                if c == "all" or c in tags[did]:
                    sb.setdefault(c, Scores()).merge(score_document(gold, before))
                    sa.setdefault(c, Scores()).merge(score_document(gold, after))
            r = controls(gold, before, after)
            for k in range(4):
                ctl[k] += r[k]
            ctl[4] += r[4]
            ctl[5] += r[5]
        out[e] = {
            "before": {c: s.summary() for c, s in sb.items()},
            "after": {c: s.summary() for c, s in sa.items()},
            "tau_same_pairs": [
                ctl[0] / ctl[1] if ctl[1] else None,
                ctl[2] / ctl[3] if ctl[3] else None,
            ],
            "text_ned_incl_author_info": [
                sum(ctl[4]) / len(ctl[4]) if ctl[4] else None,
                sum(ctl[5]) / len(ctl[5]) if ctl[5] else None,
            ],
        }

    lines = ["| 引擎 | 指标 | 之前 | 之后 |", "|---|---|---|---|"]
    for e in ENGINES:
        b, f = out[e]["before"]["all"], out[e]["after"]["all"]
        for k, name, pct in KEYS:
            lines.append(f"| {e} | {name} | {fmt(b[k], pct)} | {fmt(f[k], pct)} |")
        tb, ta = out[e]["tau_same_pairs"]
        lines.append(f"| {e} | τ（同匹配块） | {fmt(tb, False)} | {fmt(ta, False)} |")
        nb, na = out[e]["text_ned_incl_author_info"]
        lines.append(f"| {e} | 文本 NED↓（含 author_info） | {fmt(nb, False)} | {fmt(na, False)} |")

    lines += ["", "| 类型 F1 | " + " | ".join(ENGINES) + " |", "|---|" + "---|" * len(ENGINES)]
    types = sorted(
        {
            t
            for e in ENGINES
            for side in ("before", "after")
            for t in out[e][side]["all"]["per_type_f1"]
        }
    )
    for t in types:
        cells = []
        for e in ENGINES:
            vb = out[e]["before"]["all"]["per_type_f1"].get(t)
            va = out[e]["after"]["all"]["per_type_f1"].get(t)
            cells.append(f"{fmt(vb, False)} → {fmt(va, False)}")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")

    lines += ["", "按类别的变差（之前 → 之后）："]
    worse = []
    for e in ENGINES:
        for c, b in out[e]["before"].items():
            f = out[e]["after"][c]
            for k, name, _ in KEYS:
                if b[k] is None or f[k] is None:
                    continue
                if (f[k] > b[k]) if k in LOWER_BETTER else (f[k] < b[k]):
                    worse.append(f"- {e} / {c} / {name}：{b[k]} → {f[k]}")
    lines += worse or ["- 无"]
    print("\n".join(lines))
    if a.json:
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
