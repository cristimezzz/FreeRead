"""问答上下文组装：检索命中 → 加邻块与摘要 → 按预算截断 → 按阅读顺序输出 [b_xxxx] 行。

- 摘要块总是先放（帮模型了解全文在讲什么），但最多占预算的 1/4；
- 按检索名次依次加入命中块和它在同一章节内的前后邻块（检索单元常常只是半个论点）；
- 检索没有命中时（如问句里的词在正文里都不出现），退回到论文开头的段落；
- 超出预算就停；输出按阅读顺序，章节变化时加一行章节标题，标题不带编号（不希望被引用）。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

ABSTRACT_SHARE = 0.25
NEIGHBORS = 1


@dataclass
class ContextBlock:
    id: str
    type: str
    section_id: str | None
    text: str  # 已展开占位符的纯文本；空串表示不可用（参考文献、公式块、页面装饰等）


@dataclass
class QAContext:
    block_ids: list[str]  # 阅读顺序
    text: str
    tokens: int


def build_context(
    hit_ids: Sequence[str],
    blocks: Sequence[ContextBlock],
    section_titles: dict[str, str],
    token_len: Callable[[str], int],
    budget: int,
) -> QAContext:
    usable = [b for b in blocks if b.text and b.type != "heading"]
    pos = {b.id: i for i, b in enumerate(usable)}
    chosen: set[str] = set()
    used = 0

    def add(b: ContextBlock, limit: int) -> bool:
        nonlocal used
        if b.id in chosen:
            return True
        cost = token_len(b.text) + 4
        if used + cost > limit:
            return False
        chosen.add(b.id)
        used += cost
        return True

    for b in usable:
        if b.type == "abstract" and not add(b, int(budget * ABSTRACT_SHARE)):
            break

    ranked = [h for h in dict.fromkeys(hit_ids) if h in pos]
    for hid in ranked:
        i = pos[hid]
        hit = usable[i]
        if not add(hit, budget):
            break
        for j in range(i - NEIGHBORS, i + NEIGHBORS + 1):
            if j != i and 0 <= j < len(usable) and usable[j].section_id == hit.section_id:
                add(usable[j], budget)

    if not ranked:  # 没有命中：退回论文开头
        for b in usable:
            if not add(b, budget):
                break

    ordered = [b for b in usable if b.id in chosen]
    lines: list[str] = []
    section: object = object()
    for b in ordered:
        if b.section_id != section:
            section = b.section_id
            title = section_titles.get(b.section_id or "", "")
            if title:
                lines.append(f"## {title}")
        lines.append(f"[{b.id}] {b.text}")
    return QAContext([b.id for b in ordered], "\n\n".join(lines), used)
