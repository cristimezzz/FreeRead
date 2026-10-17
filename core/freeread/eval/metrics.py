"""解析评测指标（纯函数）。见 docs/01-architecture.md §9 与 docs/m0/parser-eval.md。

输入为"页级块"：(page, bbox, type, order, text, latex)。预测块来自某引擎的 Document IR，
golden 块来自 core/tests/golden/<doc_id>.json。

- 匹配：每页内按 IoU 降序贪心一对一匹配，IoU ≥ 阈值（默认 0.5）。
- 检测：precision / recall / F1（以块为单位）。
- 类型：匹配块的严格类型准确率、粗粒度准确率（见 COARSE）、各类型 F1。
- 阅读顺序：匹配块在 golden 与预测中的相对顺序的 Kendall τ（逐页计算，按对数加权平均）。
- 文本：文本类匹配块的归一化编辑距离（NED，越低越好）。
- 公式：equation 匹配块 LaTeX 规范化后的 NED。
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

COARSE = {
    "title": "heading",
    "heading": "heading",
    "paragraph": "text",
    "abstract": "text",
    "list_item": "text",
    "author_info": "text",
    "footnote": "text",
    "reference_entry": "reference",
    "caption": "caption",
    "equation": "equation",
    "figure": "figure",
    "table": "table",
    "code": "code",
    "other": "other",
}
TEXTUAL = {
    "title",
    "heading",
    "paragraph",
    "abstract",
    "list_item",
    "caption",
    "footnote",
    "reference_entry",
}


@dataclass
class PB:
    page: int
    bbox: tuple[float, float, float, float]
    type: str
    order: int
    text: str = ""
    latex: str | None = None
    id: str = ""


@dataclass
class Scores:
    n_gold: int = 0
    n_pred: int = 0
    n_match: int = 0
    type_correct: int = 0
    coarse_correct: int = 0
    tau_num: float = 0.0  # Σ τ_page × pairs_page
    tau_den: int = 0
    text_ned: list[float] = field(default_factory=list)
    latex_ned: list[float] = field(default_factory=list)
    gold_eq: int = 0
    eq_detected: int = 0  # golden equation 被匹配到且预测类型为 equation
    per_type: Counter = field(default_factory=Counter)  # (type, "tp"/"fp"/"fn")

    def merge(self, o: "Scores") -> "Scores":
        for k in (
            "n_gold",
            "n_pred",
            "n_match",
            "type_correct",
            "coarse_correct",
            "tau_den",
            "gold_eq",
            "eq_detected",
        ):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        self.tau_num += o.tau_num
        self.text_ned += o.text_ned
        self.latex_ned += o.latex_ned
        self.per_type += o.per_type
        return self

    def summary(self) -> dict:
        p = self.n_match / self.n_pred if self.n_pred else 0.0
        r = self.n_match / self.n_gold if self.n_gold else 0.0
        types = sorted({t for t, _ in self.per_type})
        per_type = {}
        for t in types:
            tp, fp, fn = (self.per_type[(t, k)] for k in ("tp", "fp", "fn"))
            per_type[t] = round(2 * tp / (2 * tp + fp + fn), 3) if tp + fp + fn else None
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
        return {
            "n_gold": self.n_gold,
            "n_pred": self.n_pred,
            "det_precision": round(p, 4),
            "det_recall": round(r, 4),
            "det_f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "type_acc": round(self.type_correct / self.n_match, 4) if self.n_match else None,
            "coarse_type_acc": round(self.coarse_correct / self.n_match, 4)
            if self.n_match
            else None,
            "reading_order_tau": round(self.tau_num / self.tau_den, 4) if self.tau_den else None,
            "text_ned": mean(self.text_ned),
            "latex_ned": mean(self.latex_ned),
            "equation_recall": round(self.eq_detected / self.gold_eq, 4) if self.gold_eq else None,
            "per_type_f1": per_type,
        }


def iou(a, b) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
    return inter / (area(a) + area(b) - inter)


def match(gold: list[PB], pred: list[PB], thr: float = 0.5) -> list[tuple[int, int]]:
    """一页内的贪心一对一匹配，返回 (gold_idx, pred_idx)。"""
    cands = []
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            v = iou(g.bbox, p.bbox)
            if v >= thr:
                cands.append((v, i, j))
    cands.sort(reverse=True)
    used_g, used_p, out = set(), set(), []
    for _, i, j in cands:
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        out.append((i, j))
    return out


def kendall_tau(xs: list[int]) -> tuple[float, int]:
    """xs 为按 golden 顺序排列的预测序号；返回 (τ, 对数)。"""
    n = len(xs)
    if n < 2:
        return 0.0, 0
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            if xs[i] < xs[j]:
                conc += 1
            elif xs[i] > xs[j]:
                disc += 1
    pairs = n * (n - 1) // 2
    return (conc - disc) / pairs, pairs


def normalize_text(s: str) -> str:
    s = re.sub(r"⟦[A-Za-z0-9_]+⟧", "", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


_LATEX_DROP = re.compile(
    r"\\(left|right|big|Big|bigg|Bigg|displaystyle|textstyle|mathrm|operatorname|rm|mathsf|mathit)\b"
)


def normalize_latex(s: str | None) -> str:
    s = s or ""
    s = _LATEX_DROP.sub("", s)
    s = re.sub(r"\\[,;:!]|\\quad|\\qquad|~", "", s)
    s = re.sub(r"\\(tag|label)\{[^}]*\}", "", s)
    s = re.sub(r"\s+", "", s)
    s = s.replace("{", "").replace("}", "")
    return s


def ned(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    return Levenshtein.normalized_distance(a, b)


def score_page(gold: list[PB], pred: list[PB], thr: float = 0.5) -> Scores:
    s = Scores(n_gold=len(gold), n_pred=len(pred))
    pairs = match(gold, pred, thr)
    s.n_match = len(pairs)
    matched_g = {i for i, _ in pairs}
    matched_p = {j for _, j in pairs}
    for i, j in pairs:
        g, p = gold[i], pred[j]
        if g.type == p.type:
            s.type_correct += 1
            s.per_type[(g.type, "tp")] += 1
        else:
            s.per_type[(g.type, "fn")] += 1
            s.per_type[(p.type, "fp")] += 1
        if COARSE.get(g.type) == COARSE.get(p.type):
            s.coarse_correct += 1
        if g.type in TEXTUAL and p.type in TEXTUAL and g.text:
            s.text_ned.append(ned(normalize_text(g.text), normalize_text(p.text)))
        if g.type == "equation" and p.type == "equation" and g.latex:
            s.latex_ned.append(ned(normalize_latex(g.latex), normalize_latex(p.latex)))
    for i, g in enumerate(gold):
        if g.type == "equation":
            s.gold_eq += 1
        if i not in matched_g:
            s.per_type[(g.type, "fn")] += 1
    s.eq_detected = sum(
        1 for i, j in pairs if gold[i].type == "equation" and pred[j].type == "equation"
    )
    for j, p in enumerate(pred):
        if j not in matched_p:
            s.per_type[(p.type, "fp")] += 1

    ordered = sorted(pairs, key=lambda ij: gold[ij[0]].order)
    tau, n = kendall_tau([pred[j].order for _, j in ordered])
    s.tau_num, s.tau_den = tau * n, n
    return s


def score_document(
    gold_pages: dict[int, list[PB]], pred_blocks: list[PB], thr: float = 0.5
) -> Scores:
    """只在 golden 覆盖的页上评分。"""
    total = Scores()
    for page, gold in gold_pages.items():
        pred = [p for p in pred_blocks if p.page == page]
        total.merge(score_page(gold, pred, thr))
    return total


def blocks_from_ir(doc: dict) -> list[PB]:
    """把 IR（dict）展开为页级块；跨页块的每个 anchor 都算一个页级块（共享 order）。"""
    out = []
    for b in doc["blocks"]:
        for a in b["anchors"]:
            out.append(
                PB(
                    page=a["page"],
                    bbox=tuple(a["bbox"]),
                    type=b["type"],
                    order=b["order"],
                    text=b.get("text") or "",
                    latex=b.get("latex"),
                    id=b["id"],
                )
            )
    return out
