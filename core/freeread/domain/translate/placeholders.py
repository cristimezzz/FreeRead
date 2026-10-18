"""翻译占位保护。见 docs/01-architecture.md §5.5。

IR 的块文本里，行内公式已经是 ⟦EQ1⟧ 这样的占位符。翻译前再把引用标记、URL、行内代码
换成 ⟦CITE1⟧ ⟦URL1⟧ ⟦CODE1⟧，翻译后校验并还原：
- 每个占位符必须恰好出现一次，不能多也不能少；
- 不要求顺序不变：中文语序调整后，"A [1] 和 B [2]" 里引用的先后可能合理地变化；
- 模型常把 ⟦CITE1⟧ 写成 ⟦ CITE1 ⟧、[[CITE1]] 或 【CITE1】，先统一回标准写法再校验。
还原时只替换本模块加的占位符；EQ 等 IR 自带的占位符保留在译文里，渲染时按块的 inlines 展开。
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from freeread.domain.ir.models import PLACEHOLDER_RE

# 数字引用：[1] [1, 2] [3–5] [1,4-6]；作者年份引用（Smith et al., 2020）语义上需要翻译，不保护
CITE_RE = re.compile(r"\[\d{1,4}(?:\s*[,，–—-]\s*\d{1,4})*\]")
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()\[\]⟦⟧\"']+[^\s<>()\[\]⟦⟧\"'.,;:!?]")
CODE_RE = re.compile(r"`[^`\n]{1,200}`")
# 模型输出里的各种变体：⟦ CITE1 ⟧、[[CITE1]]、【CITE1】、〚CITE1〛
VARIANT_RE = re.compile(r"(?:⟦|\[\[|【|〚)\s*([A-Z]{2,5}\d{1,3})\s*(?:⟧|\]\]|】|〛)")


@dataclass
class Protected:
    text: str  # 送去翻译的文本
    originals: dict[str, str] = field(default_factory=dict)  # 本模块加的占位符 → 原文
    keys: list[str] = field(default_factory=list)  # 全部占位符（含 IR 自带的），按出现顺序


class PlaceholderMismatch(ValueError):
    def __init__(self, missing: list[str], extra: list[str]) -> None:
        super().__init__(f"placeholder mismatch: missing {missing}, extra {extra}")
        self.missing = missing
        self.extra = extra


def protect(text: str) -> Protected:
    originals: dict[str, str] = {}
    counters: Counter[str] = Counter()

    def sub(kind: str, pattern: re.Pattern[str], s: str) -> str:
        parts = PLACEHOLDER_RE.split(s)  # 奇数下标是已有占位符的 key，不动
        for i in range(0, len(parts), 2):

            def repl(m: re.Match[str]) -> str:
                counters[kind] += 1
                key = f"{kind}{counters[kind]}"
                originals[key] = m.group(0)
                return f"⟦{key}⟧"

            parts[i] = pattern.sub(repl, parts[i])
        return "".join(p if i % 2 == 0 else f"⟦{p}⟧" for i, p in enumerate(parts))

    out = sub("URL", URL_RE, text)  # URL 先于引用：URL 里可能有 [1]
    out = sub("CITE", CITE_RE, out)
    out = sub("CODE", CODE_RE, out)
    return Protected(out, originals, PLACEHOLDER_RE.findall(out))


def normalize_variants(text: str) -> str:
    return VARIANT_RE.sub(lambda m: f"⟦{m.group(1)}⟧", text)


def check(protected: Protected, translated: str) -> str:
    """统一占位符写法并校验，返回规范化后的译文；不一致时抛 PlaceholderMismatch。"""
    translated = normalize_variants(translated)
    want, got = Counter(protected.keys), Counter(PLACEHOLDER_RE.findall(translated))
    if want != got:
        missing = sorted((want - got).elements())
        extra = sorted((got - want).elements())
        raise PlaceholderMismatch(missing, extra)
    return translated


def restore(protected: Protected, translated: str) -> str:
    """校验后还原本模块加的占位符。"""
    translated = check(protected, translated)
    return PLACEHOLDER_RE.sub(lambda m: protected.originals.get(m.group(1), m.group(0)), translated)
