"""识别页面装饰块：页眉、页脚、侧边栏下载水印、版权行、期刊卷期行。

快速模式（PyMuPDF）只丢弃页面上下 6% 内的短文本，漏掉的装饰块会以 paragraph 进入 IR，
总结时被模型当成依据引用。这里在送 Map 之前把它们排除。两条规则，满足其一即为装饰块：

1. 跨页重复的边缘块：块的每个锚点都在页面边缘带（上下 10%、左右 8%），
   且归一化文本（小写、数字统一、去空白）在至少 2 个不同页面的边缘带出现；
2. 固定样板：短块里出现"Downloaded from <URL>"、"All rights reserved"、版权年份、
   "Cell 162, 1051–1065"式的期刊引用行、卷期行、"(continued on next page)"；
   或者块在边缘带、去掉 DOI / URL 后几乎不剩文字（如首页角上的"doi:10.1038/… Published online"）。
   最后这条限定边缘带，是为了不误伤正文里"代码见 https://…"这类短句。

只对 paragraph / footnote / other 生效：标题、摘要、作者、章节标题、图注、表格都不动。
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

CANDIDATE_TYPES = frozenset({"paragraph", "footnote", "other"})
EDGE_Y = 0.10
EDGE_X = 0.08
MIN_REPEAT_PAGES = 2
MAX_BOILERPLATE_LEN = 400
MAX_RESIDUE_WEIGHT = 20  # 拉丁字母记 1，汉字等记 3（一个汉字约等于一个英文词的信息量）

PageSize = tuple[float, float]  # (宽, 高)，PDF 点
Anchor = tuple[int, Sequence[float]]  # (页码, bbox)


@dataclass
class DecorationCandidate:
    id: str
    type: str
    text: str
    anchors: Sequence[Anchor] = ()


# URL 只吃 ASCII 可见字符：中文行里 URL 后面常常紧跟汉字、没有空格
_URL_RE = re.compile(
    r"(?:https?://|www\.)[!-~]+|\bdoi(?:\.org)?\s*[:/]\s*[!-~]+|\b10\.\d{4,}/[!-~]+", re.IGNORECASE
)
_BOILERPLATE_RES = [
    re.compile(r"downloaded\s+from\s+(?:https?://|www\.)", re.IGNORECASE),
    re.compile(r"all\s+rights\s+reserved", re.IGNORECASE),
    # © / Elsevier 抽出来的 ª / (c) / Copyright 后面跟年份
    re.compile(r"(?:©|ª|\(c\)|copyright)\s*(?:19|20)\d\d", re.IGNORECASE),
    # Grubert et al., 2015, Cell 162, 1051–1065
    re.compile(
        r"et\s+al\.,\s*(?:19|20)\d\d,\s*[A-Z][\w.&\- ]{0,60}?\s\d+,\s*e?\d+\s*[–\-]\s*e?\d+"
    ),
    # Volume 18, Number 2, 2014 / Vol. 5, No. 3
    re.compile(r"\bvol(?:ume)?\.?\s*\d+\s*,?\s*(?:no|number|issue)\.?\s*\d+", re.IGNORECASE),
    re.compile(
        r"^\(?\s*(?:legend\s+)?(?:continued\s+)?on\s+(?:the\s+)?next\s+page\s*\)?$", re.IGNORECASE
    ),
]


def normalize_text(text: str) -> str:
    """跨页比较用：小写，数字串统一成 #，去掉所有空白和控制字符。"""
    t = re.sub(r"\d+", "#", text.lower())
    return re.sub(r"[\s\x00-\x1f]+", "", t)


def in_edge_zone(bbox: Sequence[float], page: PageSize) -> bool:
    w, h = page
    x0, y0, x1, y1 = bbox
    return y1 <= h * EDGE_Y or y0 >= h * (1 - EDGE_Y) or x1 <= w * EDGE_X or x0 >= w * (1 - EDGE_X)


def is_boilerplate(text: str, *, at_edge: bool = False) -> bool:
    """短块里出现固定样板；在边缘带时，去掉 DOI / URL 后几乎不剩文字也算。"""
    if not text or len(text) > MAX_BOILERPLATE_LEN:
        return False
    if any(r.search(text) for r in _BOILERPLATE_RES):
        return True
    if at_edge and _URL_RE.search(text):
        return _letter_weight(_URL_RE.sub("", text)) <= MAX_RESIDUE_WEIGHT
    return False


def _letter_weight(text: str) -> int:
    return sum(1 if c.isascii() else 3 for c in text if c.isalpha())


def decoration_ids(
    blocks: Iterable[DecorationCandidate], pages: Mapping[int, PageSize]
) -> set[str]:
    """返回判为页面装饰的块 id。缺页面尺寸或锚点的块只按样板规则判断。"""
    cands = [b for b in blocks if b.type in CANDIDATE_TYPES and b.text]
    edge: dict[str, str] = {}  # 块 id → 归一化文本（只记全部锚点都在边缘带的块）
    pages_by_text: dict[str, set[int]] = defaultdict(set)
    for b in cands:
        if not b.anchors or any(p not in pages for p, _ in b.anchors):
            continue
        if all(in_edge_zone(bbox, pages[p]) for p, bbox in b.anchors):
            key = normalize_text(b.text)
            if key:
                edge[b.id] = key
                pages_by_text[key].update(p for p, _ in b.anchors)
    out = set()
    for b in cands:
        key = edge.get(b.id)
        repeated = key is not None and len(pages_by_text[key]) >= MIN_REPEAT_PAGES
        if repeated or is_boilerplate(b.text, at_edge=key is not None):
            out.add(b.id)
    return out
