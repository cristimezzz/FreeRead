"""从模型回复里取出 JSON 对象：容忍 ```json 代码块、前后的说明文字。"""

import json
import re
from collections.abc import Iterator
from typing import Any


def json_objects(text: str) -> Iterator[dict[str, Any]]:
    """按出现顺序产出回复里能解析的 JSON 对象：先整段，再从每个 { 开始的完整对象（含内层对象）。

    整体结构坏掉时（如括号不配对），内层对象往往还能用。
    """
    text = text.strip()
    for candidate in (text, repair(text)):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value
            break
    start = text.find("{")
    while start >= 0:
        end = _match_brace(text, start)
        if end is not None:
            try:
                value = json.loads(text[start : end + 1])
                if isinstance(value, dict):
                    yield value
            except json.JSONDecodeError:
                pass
        start = text.find("{", start + 1)


# 对象里紧跟在 } 前面、没有冒号的孤立字符串（如 `"points":[...],"method"}`）：JSON 里一定非法，
# 删掉不改变意思。评测集 d_2ca951d5e87040a4 的 Reduce 回复每个小节结尾都多写了下一个小节的 key。
_DANGLING_KEY_RE = re.compile(r',\s*"[^"\\]{1,60}"\s*(?=\})')


def repair(text: str) -> str:
    """修复模型常见的小错误；修复后仍需能被 json.loads 解析才会被采用。

    - 删掉对象末尾没有冒号的孤立字符串；
    - 补齐结尾缺的右括号（评测集 d_2d8e7b5188a46ca6 的回复少了最后的 "]}"）。
    """
    return _close_brackets(_DANGLING_KEY_RE.sub("", text))


def _close_brackets(text: str) -> str:
    stack: list[str] = []
    in_str = escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and (not stack or stack.pop() != ch):
            return text  # 括号交错，不是"缺结尾"这种情况，不修
    if in_str:
        return text
    return text + "".join(reversed(stack))


def extract_json(text: str, required: str | None = None) -> dict[str, Any]:
    """返回第一个（含 required 键的）JSON 对象；找不到时抛 ValueError。"""
    for value in json_objects(text):
        if required is None or required in value:
            return value
    raise ValueError(
        f"回复中没有含 {required!r} 的 JSON 对象" if required else "回复中没有可解析的 JSON 对象"
    )


def _match_brace(text: str, start: int) -> int | None:
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None
