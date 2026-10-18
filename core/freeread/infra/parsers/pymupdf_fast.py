"""PyMuPDF 快速模式：只用 PDF 文本层，CPU 秒级，无公式识别、无表格结构、无 OCR。

保证无 GPU、模型未下载时仍可阅读。版面规则：
- 页眉页脚：页面顶部 / 底部 6% 内的短文本丢弃；
- 分栏：宽度 < 55% 页宽的块按中线归入左 / 右栏；通栏块把页面切成若干水平带，带内先左栏后右栏；
- 标题：首页最大字号；heading：字号明显大于正文或整块加粗的短行；
- 图注：以 Figure / Fig. / Table 开头；图片块 → figure。
"""

import asyncio
import json
import re
import statistics
from importlib.metadata import version as pkg_version
from pathlib import Path

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.base import ParserCaps, ProgressCb, RawLayout
from freeread.infra.parsers.normalize_common import CAPTION_LABEL_RE, RawBlock, build_document

MARGIN_RATIO = 0.06


class PyMuPDFFastParser:
    name = "pymupdf"

    def __init__(self) -> None:
        self.version = pkg_version("pymupdf")

    def capabilities(self) -> ParserCaps:
        return ParserCaps(formulas=False, tables=False, ocr=False, needs_gpu=False)

    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout:
        out_dir.mkdir(parents=True, exist_ok=True)
        data = await asyncio.to_thread(extract, pdf)
        (out_dir / "pymupdf.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "engine.json").write_text(
            json.dumps({"engine": "pymupdf", "engine_version": self.version}), encoding="utf-8"
        )
        progress(1.0, "pymupdf: done")
        return RawLayout(engine="pymupdf", engine_version=self.version, raw_dir=out_dir, data=data)


def extract(pdf: Path) -> dict:
    """原生输出：每页的文本块（含行内字号 / 粗体统计）与图片块，坐标已是 pt、左上原点。"""
    import pymupdf

    doc = pymupdf.open(pdf)
    pages = []
    for page in doc:
        d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
        blocks = []
        for b in d["blocks"]:
            if b.get("type") == 1:
                blocks.append({"kind": "image", "bbox": b["bbox"]})
                continue
            lines, sizes, bold_chars, chars = [], [], 0, 0
            for line in b.get("lines", []):
                t = "".join(s["text"] for s in line["spans"])
                lines.append(t)
                for s in line["spans"]:
                    n = len(s["text"].strip())
                    chars += n
                    sizes.extend([round(s["size"], 1)] * max(n, 0))
                    if s["flags"] & 16 or re.search(r"bold|black|heavy", s["font"], re.IGNORECASE):
                        bold_chars += n
            if not chars:
                continue
            blocks.append(
                {
                    "kind": "text",
                    "bbox": b["bbox"],
                    "lines": lines,
                    "size": statistics.median(sizes) if sizes else 0,
                    "bold_ratio": bold_chars / chars,
                }
            )
        pages.append({"width": page.rect.width, "height": page.rect.height, "blocks": blocks})
    return {"pages": pages}


def _inside(a, b, tol: float = 2.0) -> bool:
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out = (out + " " + ln) if out else ln
    return out


def _order_page(blocks: list[dict], width: float) -> list[dict]:
    """按"通栏带 → 左栏 → 右栏"的顺序排列。"""
    mid = width / 2
    full = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) >= width * 0.55]
    narrow = [b for b in blocks if b not in full]
    if not narrow:
        return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    full.sort(key=lambda b: b["bbox"][1])
    out: list[dict] = []
    cuts = [b["bbox"][1] for b in full] + [float("inf")]
    prev = float("-inf")
    fi = 0
    for cut in cuts:
        band = [b for b in narrow if prev <= b["bbox"][1] < cut]
        left = sorted(
            (b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 < mid), key=lambda b: b["bbox"][1]
        )
        right = sorted(
            (b for b in band if (b["bbox"][0] + b["bbox"][2]) / 2 >= mid),
            key=lambda b: b["bbox"][1],
        )
        out.extend(left + right)
        if fi < len(full):
            out.append(full[fi])
            fi += 1
        prev = cut
    return out


def normalize_extract(data: dict, pdf_sha256: str, engine_version: str):
    pages = [(p["width"], p["height"]) for p in data["pages"]]
    all_sizes = [b["size"] for p in data["pages"] for b in p["blocks"] if b["kind"] == "text"]
    body = statistics.median(all_sizes) if all_sizes else 10.0

    raw: list[RawBlock] = []
    title_done = False
    for pi, p in enumerate(data["pages"]):
        w, h = p["width"], p["height"]
        kept = []
        images = [b["bbox"] for b in p["blocks"] if b["kind"] == "image"]
        for b in p["blocks"]:
            x0, y0, x1, y1 = b["bbox"]
            if b["kind"] == "text":
                text = _join_lines(b["lines"])
                # 图内文字（坐标轴、子图标号）：极短片段或落在图片区域内
                if len(re.sub(r"\W", "", text)) < 4 or any(_inside(b["bbox"], im) for im in images):
                    continue
                in_margin = y1 < h * MARGIN_RATIO or y0 > h * (1 - MARGIN_RATIO)
                if in_margin and len(text) < 120:
                    continue
                b = {**b, "text": text}
            elif (x1 - x0) * (y1 - y0) < w * h * 0.005:
                continue  # 过小的图片（logo、装饰）
            kept.append(b)
        ordered = _order_page(kept, w)
        top_size = max((b["size"] for b in ordered if b["kind"] == "text"), default=0)
        for b in ordered:
            bbox = tuple(b["bbox"])
            if b["kind"] == "image":
                raw.append(RawBlock(type=BlockType.FIGURE, page=pi, bbox=bbox, flags=["fast_mode"]))
                continue
            text = b["text"]
            short = (
                len(text) < 150
                and not text.rstrip().endswith(".")
                and len(re.findall(r"[A-Za-z一-鿿]", text)) >= 3
            )
            prev = raw[-1] if raw else None
            if (
                title_done
                and prev is not None
                and prev.type == BlockType.TITLE
                and prev.page == pi
                and b["size"] == top_size
                and 0 <= bbox[1] - prev.bbox[3] < b["size"] * 1.2
            ):
                # 题目折行被 PyMuPDF 拆成了两个块：并回 title，免得被当成作者行
                prev.text = f"{prev.text} {text}"
                prev.bbox = (
                    min(prev.bbox[0], bbox[0]),
                    prev.bbox[1],
                    max(prev.bbox[2], bbox[2]),
                    bbox[3],
                )
                continue
            if pi == 0 and not title_done and b["size"] == top_size and b["size"] > body * 1.3:
                bt, level = BlockType.TITLE, None
                title_done = True
            elif CAPTION_LABEL_RE.match(text):
                bt, level = BlockType.CAPTION, None
            elif short and (b["size"] > body * 1.15 or b["bold_ratio"] > 0.9):
                bt = BlockType.HEADING
                level = 1 if b["size"] > body * 1.3 else 2
            else:
                bt, level = BlockType.PARAGRAPH, None
            raw.append(RawBlock(type=bt, page=pi, bbox=bbox, text=text, level=level))

    return build_document(
        raw, pdf_sha256=pdf_sha256, pages=pages, engine="pymupdf", engine_version=engine_version
    )


class PyMuPDFFastNormalizer:
    engine = "pymupdf"
    version = "0.2.0"

    def normalize(self, raw: RawLayout, pdf_sha256: str):
        data = raw.data or json.loads((raw.raw_dir / "pymupdf.json").read_text(encoding="utf-8"))
        return normalize_extract(data, pdf_sha256, raw.engine_version)
