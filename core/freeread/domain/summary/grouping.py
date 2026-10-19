"""Map 阶段的分组：按一级章节分组，相邻小组合并、过大的组切开。

- 每个块沿 section 的 parent_id 向上找到根章节（通常是 level 1），按根章节分组；
- 第一个标题之前的块（论文标题、摘要等）单独成组；
- 标题块只作为组内的小标题行，不带编号（不希望模型引用标题）；
- 相邻小组合并到约 TARGET_TOKENS；超过 MAX_TOKENS 的组按块边界切开。
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

PREAMBLE_TITLE = "标题与摘要"
TARGET_TOKENS = 3000
MAX_TOKENS = 6000


@dataclass
class SourceBlock:
    id: str
    type: str
    section_id: str | None
    text: str  # 已展开占位符的纯文本；空串表示不参与（参考文献、公式块等）


@dataclass
class Group:
    titles: list[str]
    block_ids: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    tokens: int = 0

    @property
    def title(self) -> str:
        return "、".join(dict.fromkeys(t for t in self.titles if t)) or PREAMBLE_TITLE

    @property
    def content(self) -> str:
        return "\n\n".join(self.lines)


def root_sections(sections: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """section_id → 根章节 id。"""
    parent = {s["id"]: s.get("parent_id") for s in sections}
    out: dict[str, str] = {}
    for sid in parent:
        cur, seen = sid, set()
        while parent.get(cur) and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        out[sid] = cur
    return out


def group_blocks(
    blocks: Iterable[SourceBlock],
    sections: Iterable[Mapping[str, Any]],
    token_len: Callable[[str], int],
    *,
    target: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[Group]:
    sections = list(sections)
    roots = root_sections(sections)
    titles = {s["id"]: s.get("title") or "" for s in sections}

    # 1. 按根章节切成原始组（保持阅读顺序）
    raw: list[Group] = []
    current_root: object = object()
    for b in blocks:
        root = roots.get(b.section_id) if b.section_id else None
        if root != current_root:
            raw.append(Group(titles=[titles.get(root, "") if root else PREAMBLE_TITLE]))
            current_root = root
        g = raw[-1]
        if b.type == "heading":
            if b.text and b.text != g.titles[0]:  # 根章节标题会作为组标题（# 行）出现
                g.lines.append(f"## {b.text}")
                g.tokens += token_len(b.text)
            continue
        if not b.text:
            continue
        g.lines.append(f"[{b.id}] {b.text}")
        g.block_ids.append(b.id)
        g.tokens += token_len(b.text) + 4
    raw = [g for g in raw if g.block_ids]

    # 2. 过大的组按块边界切开
    split: list[Group] = []
    for g in raw:
        if g.tokens <= max_tokens:
            split.append(g)
            continue
        part = Group(titles=list(g.titles))
        for line in g.lines:
            n = token_len(line)
            if part.block_ids and part.tokens + n > target:
                split.append(part)
                part = Group(titles=[f"{g.title}（续）"])
            part.lines.append(line)
            part.tokens += n
            if line.startswith("[") and "] " in line:
                part.block_ids.append(line[1 : line.index("]")])
        if part.block_ids:
            split.append(part)

    # 3. 相邻小组合并
    merged: list[Group] = []
    for g in split:
        last = merged[-1] if merged else None
        if last is not None and last.tokens + g.tokens <= target:
            last.titles += g.titles
            last.lines += [f"# {g.title}", *g.lines] if g.title != last.title else g.lines
            last.block_ids += g.block_ids
            last.tokens += g.tokens
        else:
            if g.lines and not g.lines[0].startswith("#"):
                g.lines.insert(0, f"# {g.title}")
            merged.append(g)
    return merged
