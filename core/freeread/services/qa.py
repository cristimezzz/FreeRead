"""单篇论文问答（线性对话）。见 docs/01-architecture.md §5.7、docs/m2/qa.md。

1. 检索：当前问题（追问时拼上上一轮问题）→ SearchService 混合检索 top-k 块；
2. 上下文：命中块加同章节邻块、摘要，按预算截断（domain/qa/context.py）；
3. 生成：qa_answer@N，要求每个论断后用 [b_xxxx] 标注出处；流式输出；
4. 校验：不存在的编号从正文删除（domain/qa/citations.py），存库与展示的引用 100% 存在；
5. 存库：qa_sessions / qa_nodes，parent_id 指向上一轮。
按需调用；和翻译、总结一样要先确认向该 provider 发送文档内容。
"""

import asyncio
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import delete, func, select

from freeread.config import DataPaths
from freeread.domain.qa.citations import strip_markers, validate_answer
from freeread.domain.qa.context import ContextBlock, build_context
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import QANodeRow, QASessionRow
from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.llm.prompts import PromptRegistry
from freeread.infra.search.chunker import approx_tokens
from freeread.services.doc_blocks import LoadedDoc, load_doc
from freeread.services.llm_preflight import PreflightError, check_provider
from freeread.services.search import SearchService
from freeread.services.settings import SettingsService
from freeread.services.summary import source_blocks
from freeread.services.translate import _lang_name

PROMPT_ID = "qa_answer"
SEARCH_K = 12
CONTEXT_BUDGET = 4000  # token
HISTORY_TURNS = 3
HISTORY_ANSWER_CHARS = 600
TITLE_CHARS = 40
_MARKER_RE = re.compile(r"\[(b_\d+)\]")


class QAError(PreflightError):
    """问答无法完成。除 preflight 的 code 外还有 bad_output。"""


class QANodeOut(BaseModel):
    id: str
    session_id: str
    parent_id: str | None
    question: str
    # 引用写成 [b_0012]，都已校验存在于该文档
    answer: str
    citations: list[str]
    untraced: bool
    # invalid_ids / out_of_context / context_ids / modes / elapsed_ms
    stats: dict[str, Any]
    model: str
    prompt_version: str
    status: Literal["ok", "stale"]
    created_at: str


class QASessionOut(BaseModel):
    id: str
    doc_id: str
    title: str
    turns: int
    created_at: str
    updated_at: str


class QASessionDetail(QASessionOut):
    nodes: list[QANodeOut]


class QAContextOut(BaseModel):
    block_ids: list[str]
    # 检索方式：没有 vector 时说明语义索引还没建，界面提示下载嵌入模型
    modes: list[Literal["fts", "vector"]]


class QADelta(BaseModel):
    text: str


Event = tuple[Literal["context", "delta", "answer"], BaseModel]


class QAService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        settings: SettingsService,
        gateway: DefaultGateway,
        prompts: PromptRegistry,
        search: SearchService,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._settings = settings
        self._gateway = gateway
        self._prompts = prompts
        self._search = search
        # 透传给 provider 的额外请求参数（评测脚本用，见 SummaryService.llm_opts）
        self.llm_opts: dict[str, Any] = {}

    # ------------------------------------------------------------ 会话

    def load(self, doc_id: str) -> LoadedDoc:
        """API 预检用：文档不存在 LookupError，未解析完成 DocumentNotReady。"""
        return load_doc(self._sessions, self._paths, doc_id)

    def list_sessions(self, doc_id: str) -> list[QASessionOut]:
        with self._sessions() as s:
            turns = (
                select(func.count(QANodeRow.id))
                .where(QANodeRow.session_id == QASessionRow.id)
                .scalar_subquery()
            )
            rows = s.execute(
                select(QASessionRow, turns)
                .where(QASessionRow.doc_id == doc_id)
                .order_by(QASessionRow.updated_at.desc())
            ).all()
            return [_session_out(r, n) for r, n in rows]

    def create_session(self, doc_id: str, title: str = "") -> QASessionOut:
        with self._sessions.begin() as s:
            row = QASessionRow(doc_id=doc_id, scope=f"doc:{doc_id}", title=title)
            s.add(row)
            s.flush()
            return _session_out(row, 0)

    def get_session(self, session_id: str) -> QASessionDetail:
        with self._sessions() as s:
            row = s.get(QASessionRow, session_id)
            if row is None:
                raise LookupError(f"对话 {session_id} 不存在")
            nodes = [_node_out(n) for n in self._nodes(s, session_id)]
            return QASessionDetail(**_session_out(row, len(nodes)).model_dump(), nodes=nodes)

    def delete_session(self, session_id: str) -> bool:
        with self._sessions.begin() as s:
            return s.execute(delete(QASessionRow).where(QASessionRow.id == session_id)).rowcount > 0

    @staticmethod
    def _nodes(s, session_id: str) -> list[QANodeRow]:
        return list(
            s.scalars(
                select(QANodeRow)
                .where(QANodeRow.session_id == session_id)
                .order_by(QANodeRow.created_at, QANodeRow.id)
            )
        )

    # ------------------------------------------------------------ 提问

    async def ask(
        self, session_id: str, question: str, lang: str | None = None
    ) -> AsyncIterator[Event]:
        started = time.perf_counter()
        question = question.strip()
        if not question:
            raise QAError("bad_request", "问题不能为空")
        session = await asyncio.to_thread(self.get_session, session_id)
        lang = lang or self._settings.get().target_lang
        doc = await asyncio.to_thread(self.load, session.doc_id)
        provider_id, model = check_provider(self._gateway, self._settings, TaskKind.QA)
        prompt = self._prompts.get(PROMPT_ID)

        previous = session.nodes[-HISTORY_TURNS:]
        query = question if not previous else f"{question} {previous[-1].question}"
        found = await self._search.search_document(doc.doc_id, query, k=SEARCH_K)
        blocks = [ContextBlock(b.id, b.type, b.section_id, b.text) for b in source_blocks(doc)]
        context = build_context(
            [h.block_id for h in found.hits],
            blocks,
            doc.section_titles,
            approx_tokens,
            CONTEXT_BUDGET,
        )
        yield "context", QAContextOut(block_ids=context.block_ids, modes=found.modes)

        history = [
            {"question": n.question, "answer": strip_markers(n.answer)[:HISTORY_ANSWER_CHARS]}
            for n in previous
        ]
        messages = prompt.render(
            target_lang=_lang_name(lang),
            title=doc.title,
            history=history,
            context=context.text,
            question=question,
        )
        parts: list[str] = []
        async for chunk in self._gateway.stream(
            TaskKind.QA, messages, prompt_id=prompt.ref, doc_id=doc.doc_id, **self.llm_opts
        ):
            if chunk.delta:
                parts.append(chunk.delta)
                yield "delta", QADelta(text=chunk.delta)
        raw = "".join(parts).strip()
        if not raw:
            raise QAError("bad_output", "模型没有返回内容")

        checked = validate_answer(raw, {b.block_id for b in doc.blocks}, set(context.block_ids))
        stats = {
            "invalid_ids": checked.invalid_ids,
            "out_of_context": checked.out_of_context,
            "context_ids": context.block_ids,
            "modes": found.modes,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        node = await asyncio.to_thread(
            self._save,
            session_id,
            previous[-1].id if previous else None,
            question,
            checked.text,
            checked.citations,
            stats,
            f"{provider_id}/{model}",
            prompt.ref,
        )
        yield "answer", node

    def _save(
        self,
        session_id: str,
        parent_id: str | None,
        question: str,
        answer: str,
        citations: list[str],
        stats: dict[str, Any],
        model: str,
        prompt_version: str,
    ) -> QANodeOut:
        with self._sessions.begin() as s:
            row = QANodeRow(
                session_id=session_id,
                parent_id=parent_id,
                question=question,
                answer=answer,
                citations=citations,
                stats=stats,
                model=model,
                prompt_version=prompt_version,
            )
            s.add(row)
            s.flush()  # 填上 created_at
            session = s.get(QASessionRow, session_id)
            if session is not None:
                session.title = session.title or _title(question)
                session.updated_at = row.created_at
            return _node_out(row)


# ---------------------------------------------------------------- 辅助


def _title(question: str) -> str:
    q = " ".join(question.split())
    return q if len(q) <= TITLE_CHARS else q[: TITLE_CHARS - 1] + "…"


def _session_out(row: QASessionRow, turns: int) -> QASessionOut:
    return QASessionOut(
        id=row.id,
        doc_id=row.doc_id,
        title=row.title,
        turns=turns,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _node_out(row: QANodeRow) -> QANodeOut:
    return QANodeOut(
        id=row.id,
        session_id=row.session_id,
        parent_id=row.parent_id,
        question=row.question,
        answer=row.answer,
        citations=list(row.citations or []),
        untraced=not row.citations,
        stats=row.stats or {},
        model=row.model,
        prompt_version=row.prompt_version,
        status=row.status,
        created_at=row.created_at,
    )


def migrate_qa(s, doc_id: str, mapping: dict[str, str]) -> int:
    """重新解析后改写答案里的引用（与译文、总结迁移同一事务，见 ParseService._store）。

    映射不上的标记删掉；有引用丢失的那一轮标 stale。返回标 stale 的轮数。
    """
    stale = 0
    nodes = s.scalars(
        select(QANodeRow)
        .join(QASessionRow, QASessionRow.id == QANodeRow.session_id)
        .where(QASessionRow.doc_id == doc_id)
    )
    for row in nodes:
        lost = False

        def repl(m: re.Match[str]) -> str:
            nonlocal lost
            new = mapping.get(m.group(1))
            if new is None:
                lost = True
                return ""
            return f"[{new}]"

        row.answer = _MARKER_RE.sub(repl, row.answer)
        old = list(row.citations or [])
        row.citations = [mapping[c] for c in old if c in mapping]
        if lost or len(row.citations) < len(old):
            row.status = "stale"
            stale += 1
    return stale
