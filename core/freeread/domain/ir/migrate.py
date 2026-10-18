"""重新解析后新旧块的对应关系。规范见 docs/02-document-ir.md §8。

1. content_hash 精确匹配（重复哈希按出现顺序一一配对）；
2. 剩下的块在同一页上模糊匹配：bbox IoU ≥ 0.5 且文本相似度 ≥ 0.5，
   或者文本相似度 ≥ 0.9（不同引擎切出的框差别可能很大）；按得分贪心一一配对；
3. 无法映射的旧块由调用方把相关引用标记为 stale。
纯函数，不依赖数据库。
"""

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher

from freeread.domain.ir.models import PLACEHOLDER_RE

IOU_MIN = 0.5
SIM_WITH_IOU = 0.5
SIM_ALONE = 0.9

_WS_RE = re.compile(r"\s+")

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class BlockRef:
    id: str
    content_hash: str
    text: str
    page: int | None  # 首个 anchor 的页码；没有 anchor 时为 None
    bbox: BBox | None


def iou(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", PLACEHOLDER_RE.sub(" ", text)).strip().lower()


def similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def map_blocks(old: list[BlockRef], new: list[BlockRef]) -> dict[str, str]:
    """返回 old_block_id → new_block_id（一对一）。"""
    mapping: dict[str, str] = {}
    by_hash: dict[str, deque[str]] = defaultdict(deque)
    for b in new:
        by_hash[b.content_hash].append(b.id)
    used: set[str] = set()
    for b in old:
        candidates = by_hash.get(b.content_hash)
        if candidates:
            nid = candidates.popleft()
            mapping[b.id] = nid
            used.add(nid)

    new_by_page: dict[int, list[BlockRef]] = defaultdict(list)
    for b in new:
        if b.id not in used and b.page is not None:
            new_by_page[b.page].append(b)

    pairs: list[tuple[float, str, str]] = []
    for o in old:
        if o.id in mapping or o.page is None:
            continue
        for n in new_by_page.get(o.page, []):
            sim = similarity(o.text, n.text)
            overlap = iou(o.bbox, n.bbox) if o.bbox and n.bbox else 0.0
            if (overlap >= IOU_MIN and sim >= SIM_WITH_IOU) or sim >= SIM_ALONE:
                pairs.append((sim + overlap, o.id, n.id))

    for _, oid, nid in sorted(pairs, key=lambda p: -p[0]):
        if oid not in mapping and nid not in used:
            mapping[oid] = nid
            used.add(nid)
    return mapping
