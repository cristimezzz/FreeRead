"""跨文档消歧的判定规则（architecture §5.7A），保守优先：宁可留两个重复实体让用户合并，
也不要把两个不同的东西并成一个。

1. 同类型、别名归一化后精确相同 → 合并（不看向量）；
2. 否则取同类型实体里余弦最高的几个，≥ CANDIDATE_SIM 的作为候选交给模型成对判定，判定为同一个才合并；
   名称里的数字不同（`ResNet-50` / `ResNet-101`、`GPT-2` / `GPT-3`）的直接视为不同，不送判定；
3. 嵌入相似度本身不直接合并：内置 multilingual-e5-small 上，版本 / 变体（BERT-base 与 BERT-large、
   CIFAR-10 与 CIFAR-100）的余弦（0.95–0.99）比很多真同义（BERT 与全称 0.86）还高，
   见 docs/m3/kg.md §测量（scripts/m3_kg_resolve_eval.py）；
4. Claim（论断）是某篇论文的具体说法，不跨文档合并；
5. 用户拆分过的实体对（kg_distinct）不再合并。
"""

import re
from enum import StrEnum

import numpy as np

from freeread.domain.kg.normalize import name_norm
from freeread.domain.kg.schema import EntityType

CANDIDATE_SIM = 0.86
TOP_K = 3
NO_CROSS_DOC = {EntityType.CLAIM}

_DIGITS = re.compile(r"\d+")


class Decision(StrEnum):
    JUDGE = "judge"  # 交给模型判定
    NEW = "new"


def decide(sim: float, a_name: str, b_name: str) -> Decision:
    if sim < CANDIDATE_SIM or numbered_variants(a_name, b_name):
        return Decision.NEW
    return Decision.JUDGE


def numbered_variants(a: str, b: str) -> bool:
    """两个名称都带数字且数字不同：同一系列的不同版本 / 规模。"""
    da, db = _DIGITS.findall(name_norm(a)), _DIGITS.findall(name_norm(b))
    return bool(da) and bool(db) and da != db


def embed_text(type_: str, name: str, description: str) -> str:
    return f"{type_}: {name}" + (f" — {description}" if description else "")


def to_blob(vector: list[float]) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def top_similar(query: np.ndarray, matrix: np.ndarray, k: int = TOP_K) -> list[tuple[int, float]]:
    """余弦相似度最高的 k 行 → [(行号, 相似度)]，高的在前。matrix 为空时返回 []。"""
    if matrix.size == 0:
        return []
    q = query / (np.linalg.norm(query) or 1.0)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    sims = (matrix @ q) / norms
    order = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in order]
