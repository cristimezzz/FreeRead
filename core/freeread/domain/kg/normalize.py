"""实体名称归一化：消歧时 alias_norm 精确相等就视为同一实体，所以这里只做不改变所指的变换。

- NFKC、casefold；希腊字母写成拉丁名（α → alpha）；
- 去掉空白、连字符、下划线、撇号（`ResNet-50` = `ResNet 50` = `resnet50`）；点保留（`GPT-3.5` ≠ `GPT-35`）；
- 去掉首尾标点、引号和英文所有格 's；
- 不做词干化：`Transformer` 和 `Transformers`（库名）可能是两个东西，交给嵌入 / LLM 判定。
"""

import re
import unicodedata

_GREEK = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "θ": "theta",
    "λ": "lambda",
    "μ": "mu",
    "π": "pi",
    "σ": "sigma",
    "τ": "tau",
    "φ": "phi",
    "ω": "omega",
}
_SEPARATORS = re.compile(r"[\s\-‐‑‒–—_·'’`]+")
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")
_POSSESSIVE = re.compile(r"['’]s$")
# "Long Short-Term Memory (LSTM)"、"长短期记忆网络（LSTM）"
_ACRONYM = re.compile(r"^(?P<full>.+?)\s*[(（]\s*(?P<short>[^()（）]{1,20}?)\s*[)）]$")


def clean_name(name: str) -> str:
    """显示用：合并空白、去掉首尾引号。"""
    return " ".join(str(name).split()).strip("\"'“”‘’ ")


def name_norm(name: str) -> str:
    s = unicodedata.normalize("NFKC", clean_name(name)).casefold()
    s = _POSSESSIVE.sub("", s)
    s = "".join(_GREEK.get(ch, ch) for ch in s)
    s = _EDGE.sub("", s)
    return _SEPARATORS.sub("", s)


def acronym_split(name: str) -> list[str]:
    """`全称 (缩写)` 拆成 [全称, 缩写]；不是这种写法时原样返回 [name]。"""
    name = clean_name(name)
    m = _ACRONYM.match(name)
    if not m:
        return [name]
    full, short = m.group("full").strip(), m.group("short").strip()
    if not name_norm(full) or not name_norm(short) or " " in short.strip():
        return [name]
    return [full, short]
