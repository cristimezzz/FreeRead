"""把 MinerU 3.x 的 middle.json（pdf_info，或 schema_version 1.0 的 pages）升级成 MinerUNormalizer
读取的 4.x 形状（docvortex.middle 2.0 的子集）。

mineru.net 等远程服务仍可能按 3.x 协议返回（顶层 pdf_info / _version_name，坐标为 pt，
页尺寸在 page_size）。只转换 MinerUNormalizer 用到的字段：
- 页：page_idx、blocks；页尺寸写到 extensions.docvortex_layout.pages，bbox 归一化到 0–1；
- 文本类块的 lines/spans 拼成 content 段列表（text / equation_inline）；
- 视觉父块（image / chart / table / code）的 blocks 改为 content 部件；
- discarded_blocks 里的脚注、旁注保留，页眉页脚页码照旧丢弃；
- merge_prev → continues_prev。
对照 mineru/backend/postprocess/legacy_schema_adapter.py（MinerU 4.0 自带的 3.4.5 适配器）。
"""

from typing import Any

from freeread.infra.parsers.normalize_common import CJK_RE

VISUAL_PARENTS = {"image", "chart", "table", "code"}
# discarded_blocks 中仍属于正文内容的类型；header / footer / page_number 不要
KEEP_DISCARDED = {"page_footnote", "aside_text"}
TYPE_ALIASES = {"abstract": "text", "phonetic": "text", "interline_equation": "equation"}


def is_legacy_middle(payload: Any) -> bool:
    if not isinstance(payload, dict) or "schema" in payload:
        return False
    return "pdf_info" in payload or (
        payload.get("schema_version") == "1.0" and isinstance(payload.get("pages"), list)
    )


def legacy_version(payload: dict) -> str | None:
    v = payload.get("_version_name") or payload.get("mineru_version")
    return v if isinstance(v, str) and v.strip() else None


def upgrade_legacy_middle(payload: dict) -> dict:
    """3.x middle.json → 4.x 形状。格式不对时抛 ValueError。"""
    pages_in = payload.get("pdf_info") if "pdf_info" in payload else payload.get("pages")
    if not isinstance(pages_in, list) or not all(isinstance(p, dict) for p in pages_in):
        raise ValueError("legacy middle.json pages must be a list of objects")
    if not pages_in:
        raise ValueError("legacy middle.json has no pages")
    layout, pages = [], []
    for i, page in enumerate(pages_in):
        idx = page.get("page_idx", i)
        size = page.get("page_size")
        if not (isinstance(size, list) and len(size) >= 2 and size[0] > 0 and size[1] > 0):
            raise ValueError(f"legacy middle.json page {idx} has no page_size")
        w, h = float(size[0]), float(size[1])
        layout.append({"page_idx": idx, "width_pt": w, "height_pt": h})
        body = page.get("para_blocks")
        if body is None:
            body = page.get("preproc_blocks") or []
        kept = [b for b in page.get("discarded_blocks") or [] if b.get("type") in KEEP_DISCARDED]
        blocks = [_block(b, w, h) for b in [*body, *kept] if isinstance(b, dict)]
        pages.append({"page_idx": idx, "blocks": blocks})
    ocr = payload.get("_ocr_enable") is True or payload.get("parse_mode") == "ocr"
    return {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "pages": pages,
        "extensions": {
            "docvortex_layout": {"version": 1, "pages": layout},
            "mineru": {"parse_mode": "ocr" if ocr else "txt"},
        },
    }


def _bbox(b: Any, w: float, h: float) -> list[float]:
    if not (isinstance(b, list) and len(b) == 4):
        return [0.0, 0.0, 0.0, 0.0]
    x0, y0, x1, y1 = (float(v) for v in b)
    return [x0 / w, y0 / h, x1 / w, y1 / h]


def _type(b: dict) -> str:
    t = b.get("type") or "text"
    if t == "title":
        return "doc_title" if b.get("level") == 1 else "paragraph_title"
    return TYPE_ALIASES.get(t, t)


def _segments(b: dict) -> list[dict]:
    """lines/spans → [{type: text|equation_inline, content}]；行间按西文加空格、
    行尾连字符接小写开头时去掉连字符（同 pymupdf_fast._join_lines），中文不加空格。"""
    segs: list[dict] = []

    def add_text(t: str) -> None:
        if segs and segs[-1]["type"] == "text":
            segs[-1]["content"] += t
        else:
            segs.append({"type": "text", "content": t})

    for line in b.get("lines") or []:
        parts = []
        for s in line.get("spans") or []:
            c = s.get("content")
            if not isinstance(c, str) or not c:
                continue
            if s.get("type") in ("inline_equation", "interline_equation"):
                parts.append(("math", c.strip()))
            else:
                parts.append(("text", c))
        if not parts:
            continue
        if segs:
            prev = segs[-1]["content"] if segs[-1]["type"] == "text" else ""
            first = parts[0][1] if parts[0][0] == "text" else ""
            if prev.endswith("-") and first[:1].islower():
                segs[-1]["content"] = prev[:-1]
            elif not (CJK_RE.match(prev[-1:]) or CJK_RE.match(first[:1])):
                add_text(" ")
        for kind, c in parts:
            if kind == "math":
                segs.append({"type": "equation_inline", "content": c})
            else:
                add_text(c)
    return segs


def _plain(b: dict) -> str:
    return "".join(s["content"] for s in _segments(b))


def _block(b: dict, w: float, h: float) -> dict:
    t = _type(b)
    out: dict[str, Any] = {"type": t, "bbox": _bbox(b.get("bbox"), w, h)}
    if b.get("merge_prev"):
        out["continues_prev"] = True
    if b.get("level") is not None:
        out["level"] = b["level"]
    children = [c for c in b.get("blocks") or [] if isinstance(c, dict)]
    if t in VISUAL_PARENTS:
        out["content"] = [_part(c, w, h) for c in children]
    elif t == "equation":
        out["content"] = _plain(b).strip()
    elif t == "list" and children:
        out["content"] = [
            {"type": "list_item", "bbox": _bbox(c.get("bbox"), w, h), "content": _segments(c)}
            for c in children
        ]
    elif children:
        # index 等带子块的其它类型：子块按顺序拼成一段
        out["content"] = [s for c in children for s in _segments(c)]
    else:
        out["content"] = _segments(b)
    return out


def _part(c: dict, w: float, h: float) -> dict:
    t = c.get("type") or ""
    part: dict[str, Any] = {"type": t, "bbox": _bbox(c.get("bbox"), w, h)}
    if t.endswith("_body"):
        spans = [s for line in c.get("lines") or [] for s in line.get("spans") or []]
        html = next((s["html"] for s in spans if isinstance(s.get("html"), str)), None)
        if t == "table_body" and html:
            part["content"] = html
        elif t == "code_body":
            part["content"] = "\n".join(
                "".join(s.get("content") or "" for s in line.get("spans") or [])
                for line in c.get("lines") or []
            )
        # 图片不下载（远程文件名在本机不存在），解析任务按 bbox 从 PDF 截图
        part["image_path"] = None
    else:
        part["content"] = _segments(c)
    return part
