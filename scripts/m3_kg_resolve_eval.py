"""M3：校准图谱消歧的嵌入阈值（domain/kg/resolve.py 的 CANDIDATE_SIM）。

用法（在 core/ 下，需要已下载内置嵌入模型，见 设置 › 嵌入）：
    .venv/Scripts/python ../scripts/m3_kg_resolve_eval.py [--models-dir <数据目录>/models]

对一组手写的实体名称对（同一个 / 不是同一个）按 resolve.embed_text 的写法嵌入，算余弦相似度，
输出 Markdown 表格和当前规则下的判定。精确别名命中（name_norm 相同）的对不需要向量，这里不列。
原则：CANDIDATE_SIM 要低于所有"同一个"的对（漏掉的只能靠用户手动合并）；
"不是同一个"的对进入判定没关系，由模型（kg_resolve）挡住。
"""

import argparse
from pathlib import Path

import numpy as np

from freeread.config import default_data_dir
from freeread.domain.kg.normalize import name_norm
from freeread.domain.kg.resolve import CANDIDATE_SIM, Decision, decide, embed_text
from freeread.infra.embedding.local import LocalEmbedder
from freeread.infra.embedding.registry import DEFAULT_MODEL, MODELS

# (类型, A, A 描述, B, B 描述, 是否同一个)
PAIRS = [
    ("Dataset", "ImageNet", "", "ILSVRC 2012", "", True),
    ("Dataset", "ImageNet", "large-scale image classification benchmark", "ImageNet-1k", "", True),
    ("Model", "BERT", "", "Bidirectional Encoder Representations from Transformers", "", True),
    ("Method", "LSTM", "", "long short-term memory", "", True),
    ("Method", "self-attention", "", "intra-attention", "", True),
    ("Metric", "top-1 accuracy", "", "top-1 acc", "", True),
    ("Metric", "BLEU", "", "BLEU score", "", True),
    ("Dataset", "COCO", "", "MS COCO", "", True),
    ("Method", "Transformer", "", "Transformer architecture", "", True),
    ("Task", "machine translation", "", "神经机器翻译", "", True),
    ("Model", "BERT-base", "", "BERT-large", "", False),
    ("Dataset", "ImageNet-1k", "", "ImageNet-21k", "", False),
    ("Model", "GPT-2", "", "GPT-3", "", False),
    ("Model", "Transformer", "", "Transformer-XL", "", False),
    ("Model", "ResNet-50", "", "ResNet-101", "", False),
    ("Dataset", "CIFAR-10", "", "CIFAR-100", "", False),
    ("Metric", "top-1 accuracy", "", "top-5 accuracy", "", False),
    ("Metric", "BLEU", "", "ROUGE-L", "", False),
    ("Dataset", "WMT14 En-De", "", "WMT14 En-Fr", "", False),
    ("Method", "dropout", "", "DropConnect", "", False),
    ("Model", "BERT", "", "RoBERTa", "", False),
    ("Task", "image classification", "", "object detection", "", False),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path, default=default_data_dir() / "models")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    embedder = LocalEmbedder(MODELS[args.model], args.models_dir)
    if not embedder.is_downloaded():
        raise SystemExit(f"内置嵌入模型不在 {args.models_dir}，先在设置里下载")

    texts = []
    for etype, a, a_desc, b, b_desc, _ in PAIRS:
        assert name_norm(a) != name_norm(b), (a, b)
        texts += [embed_text(etype, a, a_desc), embed_text(etype, b, b_desc)]
    vecs = np.asarray(embedder.embed(texts, "passage"), dtype="<f4")

    print(f"模型 {args.model}；CANDIDATE_SIM={CANDIDATE_SIM}\n")
    print("| 类型 | A | B | 同一个 | 余弦 | 判定 |")
    print("|---|---|---|---|---|---|")
    pos, neg, missed, judged = [], [], 0, 0
    for i, (etype, a, _, b, _, same) in enumerate(PAIRS):
        va, vb = vecs[2 * i], vecs[2 * i + 1]
        sim = float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb)))
        (pos if same else neg).append(sim)
        decision = decide(sim, a, b)
        judged += decision is Decision.JUDGE
        missed += same and decision is Decision.NEW
        print(f"| {etype} | {a} | {b} | {'是' if same else '否'} | {sim:.3f} | {decision} |")
    print(
        f"\n同一个：{min(pos):.3f}–{max(pos):.3f}；不是同一个：{min(neg):.3f}–{max(neg):.3f}"
        f"\n送模型判定 {judged} / {len(PAIRS)}；同一个却没送判定（漏合并）{missed} / {len(pos)}"
    )


if __name__ == "__main__":
    main()
