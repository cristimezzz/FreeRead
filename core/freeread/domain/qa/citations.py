"""问答答案的引用校验。

答案正文里的引用标记（[b_12]、【b_0012】、[b_1, b_2]、(d_…#b_0012) 等）就地规范化为
[b_0012][b_0013]；文档里不存在的编号从正文中删掉并计数。所以存库、展示的答案里，
每个引用都指向存在的块（M2 验收：100%）。
"""

from dataclasses import dataclass, field

from freeread.domain.summary.citations import INLINE_MARKER_RE, normalize_ids


@dataclass
class ValidatedAnswer:
    text: str
    citations: list[str] = field(default_factory=list)  # 按首次出现顺序、去重
    invalid_ids: int = 0  # 模型给出、但文档里不存在的编号数
    out_of_context: int = 0  # 存在于文档、但不在所给上下文里的编号数（仍保留）


def validate_answer(
    text: str, existing: set[str], context_ids: set[str] | None = None
) -> ValidatedAnswer:
    out = ValidatedAnswer(text="")
    seen_out: set[str] = set()

    def repl(m) -> str:
        ids = normalize_ids(m.group(0))
        valid = [i for i in ids if i in existing]
        out.invalid_ids += len(ids) - len(valid)
        for i in valid:
            if i not in out.citations:
                out.citations.append(i)
            if context_ids is not None and i not in context_ids and i not in seen_out:
                seen_out.add(i)
                out.out_of_context += 1
        return "".join(f"[{i}]" for i in valid)

    out.text = INLINE_MARKER_RE.sub(repl, text).strip()
    return out


def strip_markers(text: str) -> str:
    """去掉引用标记（给对话历史用：模型不需要看到上一轮的编号）。"""
    return INLINE_MARKER_RE.sub("", text).strip()
