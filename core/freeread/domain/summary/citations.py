"""引用规范化与校验。

模型给出的块编号可能写成 b_12、B_0012、d_…#b_0012，或者写在要点正文里（[b_0012]）。
统一成 b_NNNN，丢掉文档里不存在的编号；没有有效引用的要点标记 untraced（界面显示"未溯源"）。
"""

import re
from collections.abc import Iterable
from typing import Any

_ID_RE = re.compile(r"(?:d_[0-9a-fA-F]+#)?\bb[_-]?(\d{1,6})\b", re.IGNORECASE)
_INLINE_RE = re.compile(r"\s*[\[【(（]\s*(?:(?:d_[0-9a-fA-F]+#)?b[_-]?\d+[\s,，、;；]*)+[\]】)）]")
# 问答答案的就地校验也用它（domain/qa/citations.py）
INLINE_MARKER_RE = _INLINE_RE


def normalize_ids(raw: Any) -> list[str]:
    """把各种写法的编号列表 / 字符串转成去重的 b_NNNN 列表（保持顺序）。"""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in items:
        for m in _ID_RE.finditer(str(item)):
            bid = f"b_{int(m.group(1)):04d}"
            if bid not in out:
                out.append(bid)
    return out


def split_inline(text: str) -> tuple[str, list[str]]:
    """去掉正文里的 [b_0012] 式引用，返回 (正文, 引用)。"""
    ids: list[str] = []
    for m in _INLINE_RE.finditer(text):
        ids += [i for i in normalize_ids(m.group(0)) if i not in ids]
    return _INLINE_RE.sub("", text).strip(), ids


def clean_point(point: Any, existing: set[str]) -> tuple[dict[str, Any] | None, int]:
    """规范化一个要点，返回 (要点, 无效编号数)。正文为空时返回 None。"""
    if isinstance(point, str):
        point = {"text": point}
    if not isinstance(point, dict):
        return None, 0
    text, inline = split_inline(str(point.get("text") or point.get("point") or ""))
    if not text or not _ID_RE.sub("", text).strip(" ,，、;；[]【】()（）"):
        return None, 0  # 空的，或者只有块编号（结构错位时会把编号当成正文）
    ids = normalize_ids(point.get("block_ids") or point.get("citations"))
    ids += [i for i in inline if i not in ids]
    valid = [i for i in ids if i in existing]
    out: dict[str, Any] = {"text": text, "block_ids": valid}
    if not valid:
        out["untraced"] = True
    return out, len(ids) - len(valid)


def coverage_stats(points: Iterable[dict[str, Any]], invalid_ids: int = 0) -> dict[str, Any]:
    points = list(points)
    cited = sum(1 for p in points if p.get("block_ids"))
    return {
        "points": len(points),
        "cited_points": cited,
        "coverage": round(cited / len(points), 4) if points else None,
        "invalid_ids": invalid_ids,
    }
