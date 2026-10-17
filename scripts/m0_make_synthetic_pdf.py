"""生成无版权问题的合成论文 PDF，用于录制各引擎原生输出作为 Normalizer 单测 fixture。

用法：core/.venv/Scripts/python scripts/m0_make_synthetic_pdf.py
输出：core/tests/fixtures/raw/synthetic.pdf
之后对每个引擎运行 scripts/engines/run_<engine>.py，把 raw 输出（去掉图片）放进
core/tests/fixtures/raw/<engine>/。
"""

from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parents[1] / "core" / "tests" / "fixtures" / "raw" / "synthetic.pdf"

LOREM = (
    "Document understanding systems convert page images into structured text. "
    "We describe a simple pipeline that detects layout regions, orders them and "
    "recognises formulas, then evaluate it on a small benchmark of scientific articles. "
)


def box(page, x0: float, y0: float, x1: float, text: str, **kw) -> float:
    """在 (x0, y0)–x1 处写入文本框，自动增高直到放得下；返回文本框底边 y。"""
    h = 14.0
    while True:
        rc = page.insert_textbox(pymupdf.Rect(x0, y0, x1, y0 + h), text, **kw)
        if rc >= 0:
            return y0 + h - rc
        h += 12.0


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    W, H = 612, 792
    p = doc.new_page(width=W, height=H)
    box(
        p, 72, 60, 540, "A Synthetic Study of Layout Parsing", fontsize=20, fontname="hebo", align=1
    )
    box(p, 72, 98, 540, "Ada Example and Bo Sample, Example University", fontsize=10, align=1)
    box(p, 72, 125, 540, "Abstract", fontsize=11, fontname="hebo")
    y = box(p, 72, 142, 540, LOREM * 2, fontsize=9.5)

    colw, gap, top = 228, 12, y + 18
    lx, rx = 72, 72 + colw + gap
    y = box(p, lx, top, lx + colw, "1 Introduction", fontsize=11, fontname="hebo")
    y = box(p, lx, y + 4, lx + colw, LOREM * 2, fontsize=9.5)
    y = box(p, lx, y + 10, lx + colw, "2 Method", fontsize=11, fontname="hebo")
    y = box(p, lx, y + 4, lx + colw, LOREM, fontsize=9.5)
    y = box(p, lx + 30, y + 10, lx + colw, "L = - sum_i y_i log p_i        (1)", fontsize=10)
    box(p, lx, y + 10, lx + colw, LOREM, fontsize=9.5)

    # 右栏：图 + 图注 + 表 + 表注
    fig = pymupdf.Rect(rx, top, rx + colw, top + 150)
    p.draw_rect(fig, color=(0, 0, 0), width=0.8)
    for i in range(6):
        h = 20 + i * 18
        p.draw_rect(
            pymupdf.Rect(rx + 20 + i * 32, fig.y1 - 10 - h, rx + 40 + i * 32, fig.y1 - 10),
            color=(0.2, 0.3, 0.8),
            fill=(0.2, 0.3, 0.8),
        )
    y = box(
        p,
        rx,
        fig.y1 + 6,
        rx + colw,
        "Figure 1. Accuracy of each stage on the synthetic benchmark.",
        fontsize=8.5,
    )
    y = box(p, rx, y + 14, rx + colw, "Table 1. Results by block type.", fontsize=8.5)
    rows = [
        ("Type", "Precision", "Recall"),
        ("Paragraph", "0.95", "0.93"),
        ("Heading", "0.90", "0.88"),
        ("Equation", "0.81", "0.77"),
    ]
    y += 6
    for r in rows:
        for c, cell in enumerate(r):
            p.insert_text((rx + 6 + c * 76, y + 12), cell, fontsize=9)
        p.draw_line((rx, y), (rx + colw, y), width=0.5)
        y += 18
    p.draw_line((rx, y), (rx + colw, y), width=0.5)
    box(p, rx, y + 15, rx + colw, LOREM, fontsize=9.5)

    p2 = doc.new_page(width=W, height=H)
    y = box(p2, 72, 72, 540, "3 Conclusion", fontsize=11, fontname="hebo")
    y = box(p2, 72, y + 4, 540, LOREM * 2, fontsize=9.5)
    y = box(p2, 72, y + 14, 540, "References", fontsize=11, fontname="hebo")
    refs = [
        "1. Example, A. & Sample, B. Parsing pages at scale. J. Doc. Eng. 12, 1-10 (2020).",
        "2. Sample, B. Reading order for multi-column layouts. Proc. Layout Conf. 3, 45-52 (2021).",
        "3. Example, A. Formula recognition revisited. Trans. Symb. 7, 99-120 (2022).",
    ]
    for r in refs:
        y = box(p2, 72, y + 6, 540, r, fontsize=9)
    doc.set_metadata({"title": "A Synthetic Study of Layout Parsing", "author": "FreeRead tests"})
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
