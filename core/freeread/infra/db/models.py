"""M1 用到的表。结构以 docs/03-data-model.md 为准；修改模型后用 Alembic 生成迁移：

    cd core && alembic revision --autogenerate -m "<说明>"

全文检索、向量、图谱、问答、总结、术语表等表在后续里程碑加入。
"""

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freeread.infra.db.base import Base, new_ulid, utcnow

# ---------------------------------------------------------------- 文献库


class ItemRow(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    zotero_key: Mapped[str | None] = mapped_column(String, unique=True)
    zotero_library_id: Mapped[str | None] = mapped_column(String)
    zotero_version: Mapped[int | None] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String, index=True)
    venue: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="active")  # active | archived
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_items_title", "title"),)


class CollectionRow(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    zotero_key: Mapped[str | None] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"))


class ItemCollectionRow(Base):
    __tablename__ = "item_collections"

    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )


class ItemTagRow(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String, primary_key=True)


class AttachmentRow(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    zotero_key: Mapped[str | None] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String, default="application/pdf")
    sha256: Mapped[str | None] = mapped_column(String)
    doc_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.doc_id", ondelete="SET NULL"), index=True
    )


class SyncStateRow(Base):
    __tablename__ = "sync_state"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    last_version: Mapped[int | None] = mapped_column(Integer)
    last_synced_at: Mapped[str | None] = mapped_column(String)


# ---------------------------------------------------------------- 文档与块


class DocumentRow(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    pdf_sha256: Mapped[str] = mapped_column(String, unique=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    ir_path: Mapped[str | None] = mapped_column(Text)
    ir_schema_version: Mapped[str | None] = mapped_column(String)
    parser_engine: Mapped[str | None] = mapped_column(String)
    parser_version: Mapped[str | None] = mapped_column(String)
    normalizer_version: Mapped[str | None] = mapped_column(String)
    # pending | parsing | ready | failed
    parse_status: Mapped[str] = mapped_column(String, default="pending")
    embed_status: Mapped[str] = mapped_column(String, default="pending")
    kg_status: Mapped[str] = mapped_column(String, default="pending")
    language: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class BlockRow(Base):
    """ir.json 中块的可查询副本。"""

    __tablename__ = "blocks"

    doc_id: Mapped[str] = mapped_column(
        ForeignKey("documents.doc_id", ondelete="CASCADE"), primary_key=True
    )
    block_id: Mapped[str] = mapped_column(String, primary_key=True)
    ord: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    section_id: Mapped[str | None] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, default="")
    inlines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    latex: Mapped[str | None] = mapped_column(Text)
    html: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String)
    anchors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String, index=True)

    __table_args__ = (Index("ix_blocks_doc_id_ord", "doc_id", "ord"),)


class EmbeddingChunkRow(Base):
    """嵌入的检索单元。一个 chunk 可以覆盖多个相邻短块，长块也可以拆成多个 chunk。

    向量存在运行时创建的 vec0 虚拟表 vec_chunks（维度随模型），以 rowid 关联；
    blocks_fts（FTS5）在迁移 0002 中创建。两者都不在 ORM 里，见 base.include_name。
    """

    __tablename__ = "embedding_chunks"

    rowid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    ord: Mapped[int] = mapped_column(Integer)
    block_ids: Mapped[list[str]] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String)
    text_hash: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        Index("ix_embedding_chunks_doc_id_ord", "doc_id", "ord"),
        Index("ix_embedding_chunks_model_text_hash", "model", "text_hash"),
    )


# ---------------------------------------------------------------- 翻译


class TranslationRow(Base):
    # block_id 不做外键：重新解析会替换 blocks，旧译文按 IR §8 迁移或标记 stale。
    __tablename__ = "translations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    block_id: Mapped[str] = mapped_column(String)
    lang: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)  # provider/model
    prompt_version: Mapped[str] = mapped_column(String)  # 如 translate@1
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="ok")  # ok | needs_review | stale
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    __table_args__ = (
        UniqueConstraint("doc_id", "block_id", "lang", "model", "prompt_version"),
        Index("ix_translations_doc_id_lang_block_id", "doc_id", "lang", "block_id"),
    )


class GlossaryTermRow(Base):
    """术语表。scope=global 全局生效；scope=doc:<doc_id> 只对该文档生效，并覆盖全局同名条目。

    term_key 是归一化后的原文术语（小写、合并空白），用于去重；doc_id 只为删除文档时级联。
    """

    __tablename__ = "glossary_terms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    scope: Mapped[str] = mapped_column(String)
    doc_id: Mapped[str | None] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    lang: Mapped[str] = mapped_column(String)  # 目标语言
    source_term: Mapped[str] = mapped_column(Text)
    term_key: Mapped[str] = mapped_column(Text)
    target_term: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String, default="user")  # user | auto
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("scope", "lang", "term_key"),)


# ---------------------------------------------------------------- 总结


class SummaryRow(Base):
    """结构化总结。content 里的引用是本文档的块 ID，重新解析时与译文一起迁移（IR §8）。"""

    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String)  # doc:<doc_id>；以后有 collection:<id>
    template_id: Mapped[str] = mapped_column(String)
    lang: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)  # provider/model
    prompt_version: Mapped[str] = mapped_column(
        String
    )  # summarize_map@1+summarize_reduce@1+paper@1
    # {sections: [{key, name, points: [{text, block_ids, untraced?}]}]}
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="ok")  # ok | stale
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    __table_args__ = (UniqueConstraint("doc_id", "template_id", "lang"),)


# ---------------------------------------------------------------- 批注


class AnnotationRow(Base):
    """高亮与批注。start / end 是块 text（含 ⟦KEY⟧ 占位符）里的字符区间，都为空表示整块；
    quote 是区间里的原文，重新解析后靠它在新块里重新定位（IR §8），找不到时标 stale。"""

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    block_id: Mapped[str] = mapped_column(String)
    start: Mapped[int | None] = mapped_column(Integer)
    end: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String, default="yellow")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="ok")  # ok | stale
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_annotations_doc_id_block_id", "doc_id", "block_id"),)


# ---------------------------------------------------------------- 问答


class QASessionRow(Base):
    """一次问答对话。M2 只有单篇（scope=doc:<doc_id>）；以后有分类 / 全库。"""

    __tablename__ = "qa_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_qa_sessions_doc_id_updated_at", "doc_id", "updated_at"),)


class QANodeRow(Base):
    """对话里的一问一答。parent_id 指向上一轮（M2 是线性链；M3 问答画布会分叉）。

    answer 里的引用是 [b_0012] 标记，已校验都存在于该文档；citations 是按出现顺序的块 ID。
    """

    __tablename__ = "qa_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    session_id: Mapped[str] = mapped_column(ForeignKey("qa_sessions.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("qa_nodes.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[str]] = mapped_column(JSON, default=list)
    # invalid_ids / out_of_context / context_ids / modes / elapsed_ms
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String)  # provider/model
    prompt_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ok")  # ok | stale
    created_at: Mapped[str] = mapped_column(String, default=utcnow)

    __table_args__ = (Index("ix_qa_nodes_session_id_created_at", "session_id", "created_at"),)


# ---------------------------------------------------------------- 基础设施


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # queued | running | done | failed | cancelled
    status: Mapped[str] = mapped_column(String, default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    depends_on: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    started_at: Mapped[str | None] = mapped_column(String)
    finished_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("ix_jobs_status_created_at", "status", "created_at"),)


class LLMCacheRow(Base):
    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class LLMCallRow(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_ulid)
    task_kind: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    prompt_id: Mapped[str | None] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(default=False)
    doc_id: Mapped[str | None] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class SettingRow(Base):
    """应用设置，每个顶层字段一行。API Key 不存这里，存在系统钥匙串。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
