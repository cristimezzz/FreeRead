"""混合检索的结果融合：Reciprocal Rank Fusion。

各路结果只看名次、不看分数，向量距离和 bm25 不需要归一化到同一尺度。
score(block) = Σ_路 1 / (RRF_K + rank)，rank 从 1 开始。
"""

from collections.abc import Sequence

RRF_K = 60


def rrf_merge(
    rankings: dict[str, Sequence[str]], k: int = RRF_K
) -> list[tuple[str, float, list[str]]]:
    """rankings：来源名 → 按相关性排好的 key 列表（可重复，只取首次出现）。

    返回 [(key, score, 命中的来源)]，按 score 降序；同分时按来源顺序与名次稳定排序。
    """
    scores: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    for source, keys in rankings.items():
        seen: set[str] = set()
        rank = 0
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            sources.setdefault(key, []).append(source)
    order = sorted(scores, key=lambda key: -scores[key])
    return [(key, scores[key], sources[key]) for key in order]
