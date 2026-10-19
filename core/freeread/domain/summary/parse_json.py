"""从模型回复里取出 JSON 对象：容忍 ```json 代码块、前后的说明文字。"""

import json
from collections.abc import Iterator
from typing import Any


def json_objects(text: str) -> Iterator[dict[str, Any]]:
    """按出现顺序产出回复里能解析的 JSON 对象：先整段，再从每个 { 开始的完整对象（含内层对象）。

    整体结构坏掉时（如括号不配对），内层对象往往还能用。
    """
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            yield value
    except json.JSONDecodeError:
        pass
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
