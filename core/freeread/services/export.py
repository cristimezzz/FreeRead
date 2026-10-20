"""导出 Markdown：元数据、总结、批注、正文（可带译文）、问答。见 docs/m2/annotations.md。

- 正文按阅读顺序，标题按章节层级；行内公式占位符还原为 `$LaTeX$`，其余占位符去掉；
  公式块为 `$$…$$`，表格保留 HTML，图只保留图注；
- 译文：below 把译文作为引用块放在原文下面，only 有译文的块只放译文；
- 批注：正文里高亮写成 `==…==`（Obsidian / Typora 支持），批注内容写在块后面；
  另有"批注"一节按顺序列出全部高亮与批注，不导出正文时也能用；
- 总结、问答里的块引用换成页码 `[p. 3]`，导出的文件离开 FreeRead 也看得懂。
"""

import re
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select

from freeread.config import DataPaths
from freeread.domain.ir.models import PLACEHOLDER_RE, BlockType
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import AttachmentRow, ItemRow
from freeread.services.annotations import AnnotationOut, AnnotationService
from freeread.services.doc_blocks import LoadedDoc, load_doc
from freeread.services.qa import QAService
from freeread.services.settings import SettingsService
from freeread.services.summary import SummaryService
from freeread.services.translate import TranslateService

TranslationLayout = Literal["off", "below", "only"]
_MARKER_RE = re.compile(r"\s?\[(b_\d{4,})\]")
_SKIP_BODY = {BlockType.TITLE.value, BlockType.AUTHOR_INFO.value, BlockType.FIGURE.value}


class ExportOptions(BaseModel):
    lang: str | None = None  # 译文、总结的语言，默认取设置中的目标语言
    summary: bool = True
    annotations: bool = True
    body: bool = True
    translation: TranslationLayout = "below"
    qa: bool = False


def _inline_md(text: str, inlines: list[dict[str, Any]]) -> str:
    math = {il.get("key"): il.get("latex") for il in inlines or [] if il.get("kind") == "math"}

    def repl(m: re.Match[str]) -> str:
        latex = math.get(m.group(1))
        return f"${latex.strip()}$" if latex else ""

    return PLACEHOLDER_RE.sub(repl, text).strip()


def _highlight(text: str, spans: list[tuple[int, int]]) -> str:
    """在原文（含占位符）上插入 == 标记；重叠的区间合并，落在占位符中间的区间不处理。"""
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    holes = [(m.start(), m.end()) for m in PLACEHOLDER_RE.finditer(text)]
    out, last = [], 0
    for start, end in merged:
        if any(a < start < b or a < end < b for a, b in holes):
            continue
        piece = text[start:end]
        lead = len(piece) - len(piece.lstrip())
        trail = len(piece) - len(piece.rstrip())
        if not piece.strip():
            continue
        out += [text[last : start + lead], "==", piece.strip(), "=="]
        last = end - trail
    out.append(text[last:])
    return "".join(out)


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())


def _authors(authors: list[dict[str, Any]]) -> str:
    names = []
    for a in authors or []:
        name = a.get("name") or " ".join(p for p in (a.get("first"), a.get("last")) if p)
        if name:
            names.append(name)
    return ", ".join(names)


class ExportService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        translate: TranslateService,
        summary: SummaryService,
        qa: QAService,
        annotations: AnnotationService,
        settings: SettingsService,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._translate = translate
        self._summary = summary
        self._qa = qa
        self._annotations = annotations
        self._settings = settings

    def markdown(self, doc_id: str, opts: ExportOptions) -> str:
        """文档不存在抛 LookupError，尚未解析完成抛 DocumentNotReady。"""
        lang = opts.lang or self._settings.get().target_lang
        doc = load_doc(self._sessions, self._paths, doc_id)
        blocks = {b.block_id: b for b in doc.blocks}
        pages = {b.block_id: (b.anchors[0]["page"] + 1 if b.anchors else None) for b in doc.blocks}

        def cite(m: re.Match[str]) -> str:
            page = pages.get(m.group(1))
            return f" [p. {page}]" if page else ""

        def cite_ids(ids: list[str]) -> str:
            ps = sorted({p for i in ids if (p := pages.get(i))})
            return f" [p. {', '.join(map(str, ps))}]" if ps else ""

        out: list[str] = self._header(doc)
        notes = self._annotations.list_for_doc(doc_id) if opts.annotations else []

        if opts.summary:
            summaries = self._summary.list_for_doc(doc_id, lang)
            if summaries:
                s = summaries[0]
                names = {t.id: t.name for t in self._summary.templates()}
                out.append(f"## 总结（{names.get(s.template_id, s.template_id)}）\n")
                for sec in s.sections:
                    if not sec.points:
                        continue
                    out.append(f"### {sec.name}\n")
                    out += [f"- {p.text}{cite_ids(p.block_ids)}" for p in sec.points]
                    out.append("")

        if notes:
            out.append("## 批注\n")
            for a in notes:
                where = f"p. {pages[a.block_id]}" if pages.get(a.block_id) else "原文已重新解析"
                block = blocks.get(a.block_id)
                quote = _inline_md(a.quote, block.inlines if block else [])
                line = f"- =={quote}==" if quote else "- （整块）"
                out.append(f"{line} [{where}]")
                if a.note.strip():
                    out += [f"  {ln}" for ln in a.note.strip().splitlines()]
            out.append("")

        if opts.body:
            translations = (
                {t.block_id: t.text for t in self._translate.list_for_doc(doc_id, lang)}
                if opts.translation != "off"
                else {}
            )
            by_block: dict[str, list[AnnotationOut]] = {}
            for a in notes:
                by_block.setdefault(a.block_id, []).append(a)
            out.append("## 正文\n")
            out += self._body(doc, translations, opts.translation, by_block)

        if opts.qa:
            sessions = self._qa.list_sessions(doc_id)
            if sessions:
                out.append("## 问答\n")
                for meta in reversed(sessions):  # 早的在前
                    detail = self._qa.get_session(meta.id)
                    out.append(f"### {detail.title or '对话'}\n")
                    for node in detail.nodes:
                        out.append(f"**问：** {node.question.strip()}\n")
                        out.append(f"**答：** {_MARKER_RE.sub(cite, node.answer).strip()}\n")

        return "\n".join(out).rstrip() + "\n"

    # ------------------------------------------------------------ 各部分

    def _header(self, doc: LoadedDoc) -> list[str]:
        meta = doc.meta
        with self._sessions() as s:
            item = s.scalar(
                select(ItemRow)
                .join(AttachmentRow, AttachmentRow.item_id == ItemRow.id)
                .where(AttachmentRow.doc_id == doc.doc_id)
                .limit(1)
            )
            info = (
                {
                    "title": item.title,
                    "authors": item.authors,
                    "year": item.year,
                    "venue": item.venue,
                    "doi": item.doi,
                }
                if item
                else {}
            )
        title = info.get("title") or meta.get("title") or doc.title or doc.doc_id
        authors = _authors(info.get("authors") or []) or ", ".join(meta.get("authors") or [])
        facts = [
            ("作者", authors),
            ("年份", info.get("year") or meta.get("year")),
            ("期刊 / 会议", info.get("venue") or meta.get("venue")),
            ("DOI", info.get("doi") or meta.get("doi")),
        ]
        facts_md = [f"- {k}：{v}" for k, v in facts if v]
        return [f"# {title.strip()}", "", *facts_md, *([""] if facts_md else [])]

    def _body(
        self,
        doc: LoadedDoc,
        translations: dict[str, str],
        layout: TranslationLayout,
        notes: dict[str, list[AnnotationOut]],
    ) -> list[str]:
        levels = {s["id"]: s.get("level") or 1 for s in doc.sections}
        out: list[str] = []
        for b in doc.blocks:
            if b.type in _SKIP_BODY:
                continue
            mine = [a for a in notes.get(b.block_id, []) if a.status == "ok"]
            spans = [(a.start, a.end) for a in mine if a.start is not None and a.end is not None]
            source = _inline_md(_highlight(b.text, spans), b.inlines)
            if any(a.start is None for a in mine):
                source = f"=={source}==" if source else source
            translated = (
                _inline_md(translations[b.block_id], b.inlines)
                if b.block_id in translations
                else ""
            )
            text = translated if layout == "only" and translated else source
            extra = translated if layout == "below" and translated else ""

            if b.type == BlockType.HEADING.value:
                # 文档标题 #、"正文"等部分 ##，章节从 ### 起（各引擎的一级章节 level 为 1 或 2）
                depth = min(6, max(3, levels.get(b.section_id or "", 1) + 1))
                out.append(f"{'#' * depth} {text}" + (f"（{extra}）" if extra else "") + "\n")
            elif b.type == BlockType.EQUATION.value:
                out.append(f"$$\n{b.latex.strip()}\n$$\n" if b.latex else f"{text}\n")
            elif b.type == BlockType.TABLE.value:
                if b.html:
                    out.append(b.html.strip() + "\n")
                elif text:
                    out.append(text + "\n")
            elif b.type == BlockType.CAPTION.value:
                out.append(f"*{text}*\n" if text else "")
                if extra:
                    out.append(_quote(extra) + "\n")
            elif b.type in (BlockType.LIST_ITEM.value, BlockType.REFERENCE_ENTRY.value):
                out.append(f"- {text}" + (f"\n  > {extra}" if extra else "") + "\n")
            elif text:
                out.append(text + "\n")
                if extra:
                    out.append(_quote(extra) + "\n")
            for a in mine:
                if a.note.strip():
                    out.append(_quote(f"**批注**：{a.note.strip()}") + "\n")
        return out
