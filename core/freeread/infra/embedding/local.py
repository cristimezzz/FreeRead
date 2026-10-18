"""内置本地嵌入模型：onnxruntime（CPU）+ tokenizers，mean pooling 后 L2 归一化。

模型文件在 <data_dir>/models/<model_id>/，由 download() 从 Hugging Face（或镜像）获取。
推理是同步的 CPU 计算，调用方用 asyncio.to_thread；线程数取一半核，避免卡住解析和界面。
"""

import os
import threading
from pathlib import Path
from typing import Literal

import httpx
import numpy as np

from freeread.infra.embedding.downloader import DownloadItem, Progress, download_all, is_complete
from freeread.infra.embedding.registry import LocalModelSpec

BATCH = 32
DEFAULT_MIRROR = "https://huggingface.co"
Kind = Literal["passage", "query"]


class ModelNotDownloaded(RuntimeError):
    pass


class LocalEmbedder:
    def __init__(self, spec: LocalModelSpec, models_dir: Path) -> None:
        self.spec = spec
        self.dir = models_dir / spec.id
        self._lock = threading.Lock()
        self._session = None
        self._tokenizer = None

    # ---------------------------------------------------------------- 下载

    def items(self, mirror: str = DEFAULT_MIRROR) -> list[DownloadItem]:
        base = f"{mirror.rstrip('/')}/{self.spec.repo}/resolve/{self.spec.revision}"
        return [
            DownloadItem(f"{base}/{f.path}", self.dir / f.path, f.sha256, f.size)
            for f in self.spec.files
        ]

    def is_downloaded(self) -> bool:
        return all(is_complete(i) for i in self.items())

    def downloaded_bytes(self) -> int:
        total = 0
        for i in self.items():
            for p in (i.dest, i.dest.with_name(i.dest.name + ".part")):
                if p.is_file():
                    total += p.stat().st_size
        return total

    async def download(
        self, client: httpx.AsyncClient, mirror: str, progress: Progress | None = None
    ) -> None:
        await download_all(self.items(mirror), client, progress)

    # ---------------------------------------------------------------- 推理

    def _load(self):
        with self._lock:
            if self._session is None:
                if not self.is_downloaded():
                    raise ModelNotDownloaded(f"嵌入模型 {self.spec.id} 尚未下载")
                import onnxruntime as ort
                from tokenizers import Tokenizer

                opts = ort.SessionOptions()
                opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
                opts.inter_op_num_threads = 1
                self._session = ort.InferenceSession(
                    str(self.dir / self.spec.onnx), opts, providers=["CPUExecutionProvider"]
                )
                tok = Tokenizer.from_file(str(self.dir / self.spec.tokenizer))
                tok.enable_truncation(self.spec.max_tokens)
                tok.enable_padding()
                self._tokenizer = tok
            return self._session, self._tokenizer

    def token_len(self, text: str) -> int:
        _, tok = self._load()
        return len(tok.encode(text, add_special_tokens=False).ids)

    def embed(self, texts: list[str], kind: Kind = "passage") -> list[list[float]]:
        if not texts:
            return []
        session, tok = self._load()
        prefix = self.spec.query_prefix if kind == "query" else self.spec.passage_prefix
        input_names = {i.name for i in session.get_inputs()}
        # 按长度排序再分批，减少 padding
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out: list[list[float] | None] = [None] * len(texts)
        for start in range(0, len(order), BATCH):
            idx = order[start : start + BATCH]
            enc = tok.encode_batch([prefix + texts[i] for i in idx])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in input_names:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = session.run(None, feed)[0]
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            for i, vec in zip(idx, pooled, strict=True):
                out[i] = vec.astype(np.float32).tolist()
        return out  # type: ignore[return-value]

    def unload(self) -> None:
        with self._lock:
            self._session = None
            self._tokenizer = None
