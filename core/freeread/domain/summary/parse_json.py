"""从模型回复里取出 JSON 对象：容忍 ```json 代码块、前后的说明文字。"""

import json
from typing import Any


def extract_json(text: str) -> dict[str, Any]:
    """返回回复中第一个能解析的 JSON 对象；找不到时抛 ValueError。"""
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start >= 0:
        end = _match_brace(text, start)
        if end is not None:
            try:
                value = json.loads(text[start : end + 1])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
        start = text.find("{", start + 1)
    raise ValueError("回复中没有可解析的 JSON 对象")


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
