"""总结评测：引用覆盖率、引用有效率，以及供人工抽检忠实度的对照稿。

- 引用覆盖率 = 有有效引用的要点 / 全部要点（M2 验收：≥ 90%）；
- 引用有效率 = 有效引用数 / 模型给出的全部引用数（无效 = 文档里不存在的块编号）；
- 忠实度（引用的块是否支持该结论）无法自动判断：dump_review_markdown 把每条要点和它引用的原文
  并排列出，人工抽检。
"""

from collections.abc import Iterable, Mapping
from typing import Any


def iter_points(sections: Iterable[Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
    for sec in sections:
        yield from sec.get("points", [])


def citation_coverage(sections: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """返回 (有引用的要点数, 要点总数)。"""
    points = list(iter_points(sections))
    return sum(1 for p in points if p.get("block_ids")), len(points)


def citation_validity(sections: Iterable[Mapping[str, Any]], invalid_ids: int) -> tuple[int, int]:
    """返回 (有效引用数, 模型给出的引用总数)。sections 里的引用已经过校验，无效的只剩计数。"""
    valid = sum(len(p.get("block_ids", [])) for p in iter_points(sections))
    return valid, valid + invalid_ids


def dump_review_markdown(
    title: str, sections: Iterable[Mapping[str, Any]], block_text: Mapping[str, str]
) -> str:
    lines = [f"# {title}", "", "每条要点下面是它引用的原文，请判断原文是否支持该要点。", ""]
    for sec in sections:
        lines += [f"## {sec.get('name') or sec.get('key')}", ""]
        for i, p in enumerate(sec.get("points", []), 1):
            flag = " **（未溯源）**" if not p.get("block_ids") else ""
            lines.append(f"{i}. {p['text']}{flag}")
            for bid in p.get("block_ids", []):
                quote = " ".join(block_text.get(bid, "（块不存在）").split())[:400]
                lines.append(f"   - `{bid}` {quote}")
            lines.append("   - 支持？ [ ] 是 [ ] 部分 [ ] 否")
        lines.append("")
    return "\n".join(lines)
