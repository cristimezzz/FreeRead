"""问答评测的指标与对照稿。

- 展示引用有效率：校验后答案里的引用都必须存在于文档（M2 验收：100%）；
- 原始引用有效率：模型给出的编号里有多少是真的（校验删掉的计入无效）；
- 有引用的答案比例；引用不在所给上下文里的比例（模型从别处"记得"的编号）；
- 陷阱题（论文里多半没有答案）：理想表现是不给引用、说明没找到。
忠实度（引用是否支持论断）要人工看 dump_review_markdown 生成的对照稿。
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

MARKER_RE = re.compile(r"\[(b_\d+)\]")
NO_ANSWER_HINTS = ("没有找到", "未找到", "没有提到", "未提及", "not found", "does not mention")


def answer_metrics(node: Mapping[str, Any], existing: set[str]) -> dict[str, Any]:
    """一个回答的统计。node 为 QANodeOut 的 dict。"""
    shown = MARKER_RE.findall(node["answer"])
    invalid = int(node.get("stats", {}).get("invalid_ids", 0))
    return {
        "shown": len(shown),
        "shown_valid": sum(1 for i in shown if i in existing),
        "raw_total": len(shown) + invalid,
        "raw_invalid": invalid,
        "cited": bool(node["citations"]),
        "out_of_context": int(node.get("stats", {}).get("out_of_context", 0)),
        "says_no_answer": any(h in node["answer"].lower() for h in NO_ANSWER_HINTS),
    }


def dump_review_markdown(
    title: str, turns: Iterable[tuple[str, Mapping[str, Any]]], block_text: Mapping[str, str]
) -> str:
    """turns：[(问题 id, QANodeOut dict)]。每个回答后列出引用的原文，供人工判断是否支持。"""
    lines = [f"# {title}", "", "每个回答后面是它引用的原文，请判断原文是否支持回答里的论断。", ""]
    for qid, node in turns:
        lines += [f"## {qid}：{node['question']}", "", node["answer"], ""]
        if not node["citations"]:
            lines += ["（没有引用）", ""]
        for bid in node["citations"]:
            quote = " ".join(block_text.get(bid, "（块不存在）").split())[:400]
            lines.append(f"- `{bid}` {quote}")
        lines += ["", "支持？ [ ] 是 [ ] 部分 [ ] 否", ""]
    return "\n".join(lines)
