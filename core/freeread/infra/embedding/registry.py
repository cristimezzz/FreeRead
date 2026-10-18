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
    )
}

DEFAULT_MODEL = "multilingual-e5-small"
