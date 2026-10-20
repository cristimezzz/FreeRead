"""校验抽取结果：一组（章节组）的模型输出 → 本组实体与关系；再把各组合并成整篇的图。

出处是硬约束（architecture §5.7A）：
- 关系的 block_id 必须是本组给出的块，否则丢弃；
- evidence 必须能在出处块里找到（忽略大小写、空白和连字符写法），找不到就清空并降低 confidence；
- achieves 的数值必须在出处块的文本里出现（按数值比较，85.30 = 85.3），否则丢弃整条关系——
  M3 验收要求答案里的每个数值都能跳回原文。
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from freeread.domain.kg.normalize import acronym_split, clean_name, name_norm
from freeread.domain.kg.schema import EntityType, RelationType, entity_type, relation_type
from freeread.domain.summary.citations import normalize_ids

MAX_NAME = 200
MAX_DESCRIPTION = 300
MAX_EVIDENCE = 200
MAX_ALIASES = 10
MAX_VALUE_TEXT = 40
DEFAULT_CONFIDENCE = 0.8
UNSUPPORTED_EVIDENCE_PENALTY = 0.7


@dataclass
class LocalEntity:
    type: EntityType
    name: str
    aliases: list[str]  # 含 name，按 name_norm 去重
    description: str = ""
    mentions: dict[str, str] = field(default_factory=dict)  # block_id → 原文写法

    def norms(self) -> list[str]:
        return list(dict.fromkeys(n for a in self.aliases if (n := name_norm(a))))


@dataclass
class LocalRelation:
    src: int  # 实体下标
    dst: int
    type: RelationType
    block_id: str
    evidence: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)
    confidence: float = DEFAULT_CONFIDENCE


@dataclass
class DocGraph:
    entities: list[LocalEntity]
    relations: list[LocalRelation]
    stats: Counter = field(default_factory=Counter)


_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—−", "-"))
_ELLIPSIS_RE = re.compile(r"\.{3}|…+")


def _compact(text: str) -> str:
    """比较摘句用：NFKC、统一连字符、忽略大小写，去掉所有空白。

    PDF 换行会在中文里插入空格（"同义保 真度"），英文里有时又丢掉空格（"BD Canto II" → "BDCantoII"）。
    """
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).casefold()
    return "".join(text.split())


def evidence_in_text(evidence: str, text: str) -> bool:
    """摘句能在原文里找到；模型用省略号截断的摘句，各段按顺序都找得到也算。"""
    parts = [p for p in (_compact(x) for x in _ELLIPSIS_RE.split(evidence)) if p]
    body, pos = _compact(text), 0
    for p in parts:
        i = body.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return bool(parts)


# ------------------------------------------------------------ 数值


# 不取名称里的数字：ResNet-50 的 50、F1 的 1、v2.1 的 2.1。只看拉丁字母和数字：
# 中文紧挨着数字很常见（"为66.5h"、"增加41倍"）
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_.])(?<![A-Za-z][-‐])[-+−]?\d+(?:[.,]\d+)*")


def _to_float(s: str) -> float | None:
    s = s.replace("−", "-")
    if "," in s:
        # 1,234 / 12,345,678 是千分位；85,3 是小数逗号
        parts = s.lstrip("+-").split(",")
        if all(len(p) == 3 for p in parts[1:]) and "." not in parts[-1]:
            s = s.replace(",", "")
        elif s.count(",") == 1 and "." not in s:
            s = s.replace(",", ".")
        else:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def numbers_in(text: str) -> list[float]:
    return [v for m in _NUM_RE.finditer(text) if (v := _to_float(m.group(0))) is not None]


def parse_value(raw: Any) -> tuple[float, str] | None:
    """模型给的数值 → (数值, 显示用的原写法)。`85.3%`、`<50`、`0.07 ± 0.05` 都可以：
    核对用第一个数，显示保留比较符号、误差和单位（太长时只留数字本身）。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw), repr(raw) if isinstance(raw, float) else str(raw)
    text = clean_name(str(raw or ""))
    m = _NUM_RE.search(text)
    if not m:
        return None
    v = _to_float(m.group(0))
    if v is None:
        return None
    return v, text if len(text) <= MAX_VALUE_TEXT else m.group(0)


def value_in_text(value: float, text: str) -> bool:
    return any(abs(v - value) <= 1e-9 * max(1.0, abs(value)) for v in numbers_in(text))


# ------------------------------------------------------------ 一组


def _aliases(name: str, raw_aliases: Any) -> list[str]:
    out: dict[str, str] = {}
    candidates = [*acronym_split(name)]
    if isinstance(raw_aliases, list):
        for a in raw_aliases:
            if isinstance(a, str):
                candidates += acronym_split(a)
    for a in candidates:
        a = clean_name(a)[:MAX_NAME]
        n = name_norm(a)
        if n and n not in out:
            out[n] = a
    return list(out.values())[:MAX_ALIASES]


_LATIN = re.compile(r"^[\w\s\-./+()'’]+$", re.ASCII)


def _find_surface(aliases: Iterable[str], text: str) -> str | None:
    """块里出现的别名（长的优先）。拉丁文字按词边界匹配（`BERT` 不命中 `RoBERTa`），其他按子串。"""
    for a in sorted(aliases, key=len, reverse=True):
        if len(a) < 2:
            continue
        body = r"\s+".join(re.escape(p) for p in a.split())
        if _LATIN.match(a):
            body = rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"
        if re.search(body, text, re.IGNORECASE):
            return a
    return None


def parse_group(
    raw: Mapping[str, Any], block_texts: Mapping[str, str]
) -> tuple[list[LocalEntity], list[LocalRelation], Counter]:
    """block_texts：本组可引用的块 → 纯文本。返回 (实体, 关系, 丢弃统计)。"""
    stats: Counter = Counter()
    entities: list[LocalEntity] = []
    by_key: dict[str, int] = {}
    for item in raw.get("entities") or []:
        if not isinstance(item, Mapping):
            stats["bad_entities"] += 1
            continue
        etype = entity_type(item.get("type"))
        name = clean_name(str(item.get("name") or ""))[:MAX_NAME]
        if etype is None or not name_norm(name):
            stats["bad_entities"] += 1
            continue
        aliases = _aliases(name, item.get("aliases"))
        name = aliases[0]
        ent = LocalEntity(
            etype, name, aliases, clean_name(str(item.get("description") or ""))[:MAX_DESCRIPTION]
        )
        claimed = [b for b in normalize_ids(item.get("block_ids")) if b in block_texts]
        for bid, text in block_texts.items():
            surface = _find_surface(aliases, text)
            if surface is not None:
                ent.mentions[bid] = surface
        for bid in claimed:
            ent.mentions.setdefault(bid, name)
        key = str(item.get("id") or item.get("key") or name)
        by_key[key] = len(entities)
        by_key.setdefault(name, len(entities))
        entities.append(ent)

    relations: list[LocalRelation] = []
    for item in raw.get("relations") or []:
        if not isinstance(item, Mapping):
            stats["bad_relations"] += 1
            continue
        rtype = relation_type(item.get("type"))
        src, dst = by_key.get(str(item.get("src"))), by_key.get(str(item.get("dst")))
        if rtype is None or src is None or dst is None or src == dst:
            stats["bad_relations"] += 1
            continue
        ids = [b for b in normalize_ids(item.get("block_id") or item.get("block_ids"))]
        bid = next((b for b in ids if b in block_texts), None)
        if bid is None:
            stats["no_source"] += 1
            continue
        text = block_texts[bid]
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence", DEFAULT_CONFIDENCE))))
        except (TypeError, ValueError):
            confidence = DEFAULT_CONFIDENCE
        evidence = clean_name(str(item.get("evidence") or ""))[:MAX_EVIDENCE]
        if evidence and not evidence_in_text(evidence, text):
            evidence = ""
            confidence *= UNSUPPORTED_EVIDENCE_PENALTY
            stats["unsupported_evidence"] += 1

        attrs: dict[str, Any] = {}
        raw_attrs = item.get("attrs") if isinstance(item.get("attrs"), Mapping) else {}
        if rtype is RelationType.ACHIEVES:
            parsed = parse_value(raw_attrs.get("value"))
            if parsed is None or not value_in_text(parsed[0], text):
                stats["unverified_values"] += 1
                continue
            attrs["value"], attrs["value_text"] = parsed
            for k in ("metric", "unit", "dataset", "setting"):
                v = clean_name(str(raw_attrs.get(k) or ""))[:MAX_NAME]
                if v:
                    attrs[k] = v
        relations.append(LocalRelation(src, dst, rtype, bid, evidence, attrs, confidence))
        for idx in (src, dst):
            ent = entities[idx]
            ent.mentions.setdefault(bid, _find_surface(ent.aliases, text) or ent.name)

    # 没有任何出处（既没提及块也没关系）的实体不要
    used = {r.src for r in relations} | {r.dst for r in relations}
    keep = [i for i, e in enumerate(entities) if e.mentions or i in used]
    stats["bad_entities"] += len(entities) - len(keep)
    remap = {old: new for new, old in enumerate(keep)}
    entities = [entities[i] for i in keep]
    for r in relations:
        r.src, r.dst = remap[r.src], remap[r.dst]
    return entities, relations, stats


# ------------------------------------------------------------ 整篇


def merge_groups(
    groups: Iterable[tuple[list[LocalEntity], list[LocalRelation], Counter]],
) -> DocGraph:
    """同类型且任一别名归一化后相同的实体合并；关系按 (src, dst, type, block) 去重，保留高 confidence。"""
    out = DocGraph([], [])
    index: dict[tuple[EntityType, str], int] = {}
    seen: dict[tuple[int, int, RelationType, str], int] = {}
    for entities, relations, stats in groups:
        out.stats.update(stats)
        local_to_doc: list[int] = []
        for ent in entities:
            norms = ent.norms()
            hit = next((index[(ent.type, n)] for n in norms if (ent.type, n) in index), None)
            if hit is None:
                hit = len(out.entities)
                out.entities.append(
                    LocalEntity(ent.type, ent.name, [], ent.description, dict(ent.mentions))
                )
            target = out.entities[hit]
            have = {name_norm(a) for a in target.aliases}
            for a in ent.aliases:
                if name_norm(a) not in have and len(target.aliases) < MAX_ALIASES:
                    target.aliases.append(a)
                    have.add(name_norm(a))
            for bid, surface in ent.mentions.items():
                target.mentions.setdefault(bid, surface)
            if not target.description and ent.description:
                target.description = ent.description
            for n in target.norms():
                index.setdefault((ent.type, n), hit)
            local_to_doc.append(hit)
        for r in relations:
            src, dst = local_to_doc[r.src], local_to_doc[r.dst]
            if src == dst:
                continue
            key = (src, dst, r.type, r.block_id)
            if key in seen:
                prev = out.relations[seen[key]]
                if r.confidence > prev.confidence:
                    out.relations[seen[key]] = LocalRelation(
                        src, dst, r.type, r.block_id, r.evidence, r.attrs, r.confidence
                    )
                continue
            seen[key] = len(out.relations)
            out.relations.append(
                LocalRelation(src, dst, r.type, r.block_id, r.evidence, r.attrs, r.confidence)
            )
    return out
