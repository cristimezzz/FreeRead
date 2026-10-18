"""把块转成可检索的纯文本：FTS 索引与嵌入 chunk 共用。

- 占位符 ⟦KEY⟧ 按 inlines 展开：行内公式换成 LaTeX 源码，其余（cite / xref / url / code）
  只是位置标记，去掉；
- 表格取 HTML 的单元格文本（<math> 保留 LaTeX）；
- 公式块、图、参考文献条目等不参与检索。
"""

import html as html_lib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from freeread.domain.ir.models import PLACEHOLDER_RE, TRANSLATABLE_TYPES, BlockType

SEARCHABLE_TYPES = frozenset(t.value for t in TRANSLATABLE_TYPES) | {BlockType.TABLE.value}

_TAG_RE = re.compile(r"<[^>]+>")
_CELL_END_RE = re.compile(r"</t[dh]>|</tr>|<br\s*/?>", re.IGNORECASE)
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")


def expand_placeholders(text: str, inlines: Iterable[Mapping[str, Any]]) -> str:
    math = {il.get("key"): il.get("latex") for il in inlines if il.get("kind") == "math"}

    def repl(m: re.Match[str]) -> str:
        latex = math.get(m.group(1))
        return f" {latex} " if latex else " "

    return PLACEHOLDER_RE.sub(repl, text)


def table_text(html: str) -> str:
    s = _CELL_END_RE.sub(" ", html)
    s = re.sub(r"<math>(.*?)</math>", r" \1 ", s, flags=re.IGNORECASE | re.DOTALL)
    return html_lib.unescape(_TAG_RE.sub("", s))


def block_plain_text(
    type_: str, text: str, inlines: Iterable[Mapping[str, Any]], html: str | None
) -> str:
    """不可检索的块类型返回空串。"""
    if type_ not in SEARCHABLE_TYPES:
        return ""
    if type_ == BlockType.TABLE.value:
        body = table_text(html) if html else text
    else:
        body = expand_placeholders(text, inlines)
    return _SPACE_RE.sub(" ", body).strip()
