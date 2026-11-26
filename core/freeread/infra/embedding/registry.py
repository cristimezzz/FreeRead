"""内置嵌入模型表。文件固定到 Hugging Face 的某个 revision，并逐个校验 sha256。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFile:
    path: str  # 仓库内路径，也是本地相对路径
    sha256: str
    size: int


@dataclass(frozen=True)
class LocalModelSpec:
    id: str
    label: str
    repo: str
    revision: str
    files: tuple[ModelFile, ...]
    onnx: str  # files 里的 ONNX 模型路径
    tokenizer: str  # files 里的 tokenizer.json 路径
    dim: int
    max_tokens: int
    query_prefix: str = ""
    passage_prefix: str = ""
    license: str = ""
    description: str = ""

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def key(self) -> str:
        """写进 embedding_chunks.model / 向量索引状态，区分不同来源的向量。"""
        return f"local/{self.id}"


MODELS: dict[str, LocalModelSpec] = {
    spec.id: spec
    for spec in (
        LocalModelSpec(
            id="multilingual-e5-small",
            label="multilingual-e5-small（int8，中英等多语言）",
            description="适合中文、英文和跨语言检索，兼顾下载体积和索引速度。",
            # intfloat/multilingual-e5-small 的 ONNX 转换版（MIT）
            repo="Xenova/multilingual-e5-small",
            revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
            files=(
                ModelFile(
                    "onnx/model_quantized.onnx",
                    "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
                    118_308_185,
                ),
                ModelFile(
                    "tokenizer.json",
                    "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
                    17_082_730,
                ),
            ),
            onnx="onnx/model_quantized.onnx",
            tokenizer="tokenizer.json",
            dim=384,
            max_tokens=512,
            query_prefix="query: ",
            passage_prefix="passage: ",
            license="MIT",
        ),
        LocalModelSpec(
            id="e5-small-v2",
            label="e5-small-v2（英文轻量）",
            description="下载体积最小，仅适用于英文文献和英文查询。",
            repo="Xenova/e5-small-v2",
            revision="02af79985278377e65c724a76275707cb0333c70",
            files=(
                ModelFile(
                    "onnx/model_quantized.onnx",
                    "7d9092cb25f2bd1c023b7e8d2aa459044a02030ac880e5a59fdaf27af69f1ded",
                    34_014_367,
                ),
                ModelFile(
                    "tokenizer.json",
                    "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
                    711_396,
                ),
            ),
            onnx="onnx/model_quantized.onnx",
            tokenizer="tokenizer.json",
            dim=384,
            max_tokens=512,
            query_prefix="query: ",
            passage_prefix="passage: ",
            license="MIT",
        ),
        LocalModelSpec(
            id="multilingual-e5-base",
            label="multilingual-e5-base（多语言进阶）",
            description="适合多语言和跨语言检索，需要更多磁盘空间和 CPU 算力。",
            repo="Xenova/multilingual-e5-base",
            revision="1ec9243030a27d1a115d5c340572074c125b58b2",
            files=(
                ModelFile(
                    "onnx/model_quantized.onnx",
                    "df7a9a29309e3ad491e1783adf8baee710262cc06079c7cbab63c630277fac94",
                    278_647_662,
                ),
                ModelFile(
                    "tokenizer.json",
                    "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
                    17_082_660,
                ),
            ),
            onnx="onnx/model_quantized.onnx",
            tokenizer="tokenizer.json",
            dim=768,
            max_tokens=512,
            query_prefix="query: ",
            passage_prefix="passage: ",
            license="MIT",
        ),
    )
}

DEFAULT_MODEL = "multilingual-e5-small"
