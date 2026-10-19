"""读取一篇已解析文档的块与章节结构（嵌入、总结共用）。

块来自 blocks 表（按阅读顺序）；章节只存在 ir.json 里（sections 是扁平列表，
用 parent_id 组成树，见 docs/02-document-ir.md）。
"""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from freeread.config import DataPaths
from freeread.domain.ir.models import BlockType
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import BlockRow, DocumentRow


class DocumentNotReady(LookupError):
    """文档存在但还没有可用的解析结果（API 返回 409）。"""


@dataclass
class LoadedDoc:
    doc_id: str
    language: str | None
    blocks: list[BlockRow]
    sections: list[dict[str, Any]]

    @property
    def title(self) -> str:
        return next((b.text for b in self.blocks if b.type == BlockType.TITLE.value), "")

    @property
    def section_titles(self) -> dict[str, str]:
        return {s["id"]: s.get("title") or "" for s in self.sections}


def load_doc(sessions: SessionFactory, paths: DataPaths, doc_id: str) -> LoadedDoc:
    """文档不存在抛 LookupError；尚未解析完成抛 DocumentNotReady。"""
    with sessions() as s:
        doc = s.get(DocumentRow, doc_id)
        if doc is None:
            raise LookupError(f"文档 {doc_id} 不存在")
        if doc.parse_status != "ready":
            raise DocumentNotReady(f"文档 {doc_id} 尚未解析完成")
        blocks = list(
            s.scalars(select(BlockRow).where(BlockRow.doc_id == doc_id).order_by(BlockRow.ord))
        )
        ir_rel, language = doc.ir_path, doc.language
    sections: list[dict[str, Any]] = []
    if ir_rel:
        ir_path = paths.root / ir_rel
        if ir_path.is_file():
            sections = json.loads(ir_path.read_text(encoding="utf-8")).get("sections", [])
    return LoadedDoc(doc_id, language, blocks, sections)
