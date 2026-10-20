"""高亮与批注。见 docs/m2/annotations.md。

批注挂在块上：start / end 是块 text（含 ⟦KEY⟧ 占位符）里的字符区间，都为空表示整块。
重新解析后块 ID 和文本可能都变了（快速模式 → MinerU）：先按块映射（IR §8）找到新块，
再用 quote 在新块里重新定位；新块里没有时在全文里找唯一出现的位置；都找不到时标 stale，
批注本身保留（用户写的内容不能丢）。
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import AnnotationRow, BlockRow, DocumentRow

Color = Literal["yellow", "green", "blue", "pink", "purple"]


class AnnotationOut(BaseModel):
    id: str
    doc_id: str
    block_id: str
    start: int | None
    end: int | None
    quote: str
    color: Color
    note: str
    status: Literal["ok", "stale"]
    created_at: str
    updated_at: str


class AnnotationIn(BaseModel):
    block_id: str
    # 都不给表示整块（如图、表、公式）
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    color: Color = "yellow"
    note: str = Field(default="", max_length=10000)


class AnnotationPatch(BaseModel):
    color: Color | None = None
    note: str | None = Field(default=None, max_length=10000)


class AnnotationError(ValueError):
    """请求不合法（块不存在、区间越界）。"""


def _to_out(row: AnnotationRow) -> AnnotationOut:
    return AnnotationOut.model_validate(row, from_attributes=True)


class AnnotationService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def list_for_doc(self, doc_id: str) -> list[AnnotationOut]:
        """按阅读顺序（块顺序、块内位置）排列；块已不存在的 stale 批注排在最后。"""
        with self._sessions() as s:
            order: dict[str, int] = {
                bid: ord_
                for bid, ord_ in s.execute(
                    select(BlockRow.block_id, BlockRow.ord).where(BlockRow.doc_id == doc_id)
                )
            }
            rows = s.scalars(select(AnnotationRow).where(AnnotationRow.doc_id == doc_id)).all()
            out = [_to_out(r) for r in rows]
        return sorted(
            out,
            key=lambda a: (order.get(a.block_id, 1 << 30), a.start or 0, a.created_at),
        )

    def create(self, doc_id: str, body: AnnotationIn) -> AnnotationOut:
        with self._sessions.begin() as s:
            if s.get(DocumentRow, doc_id) is None:
                raise LookupError(f"文档 {doc_id} 不存在")
            block = s.get(BlockRow, (doc_id, body.block_id))
            if block is None:
                raise AnnotationError(f"块 {body.block_id} 不存在")
            start, end = body.start, body.end
            if (start is None) != (end is None):
                raise AnnotationError("start 和 end 要么都给，要么都不给")
            if start is not None and end is not None:
                if not (0 <= start < end <= len(block.text)):
                    raise AnnotationError("区间超出块文本范围")
                quote = block.text[start:end]
            else:
                quote = block.text
            row = AnnotationRow(
                doc_id=doc_id,
                block_id=body.block_id,
                start=start,
                end=end,
                quote=quote,
                color=body.color,
                note=body.note,
            )
            s.add(row)
            s.flush()
            return _to_out(row)

    def update(self, annotation_id: str, patch: AnnotationPatch) -> AnnotationOut:
        with self._sessions.begin() as s:
            row = s.get(AnnotationRow, annotation_id)
            if row is None:
                raise LookupError(f"批注 {annotation_id} 不存在")
            if patch.color is not None:
                row.color = patch.color
            if patch.note is not None:
                row.note = patch.note
            s.flush()
            return _to_out(row)

    def delete(self, annotation_id: str) -> bool:
        with self._sessions.begin() as s:
            return (
                s.execute(delete(AnnotationRow).where(AnnotationRow.id == annotation_id)).rowcount
                > 0
            )


def _nearest(text: str, quote: str, near: int) -> int | None:
    """quote 在 text 里离 near 最近的出现位置。"""
    best: int | None = None
    i = text.find(quote)
    while i != -1:
        if best is None or abs(i - near) < abs(best - near):
            best = i
        i = text.find(quote, i + 1)
    return best


def migrate_annotations(s, doc_id: str, mapping: dict[str, str], new_texts: dict[str, str]) -> int:
    """重新解析后改写块 ID 与区间（与译文、总结迁移同一事务，见 ParseService._store）。

    new_texts：新 IR 的 块 ID → text。返回标 stale 的条数。
    """
    stale = 0
    for row in s.scalars(select(AnnotationRow).where(AnnotationRow.doc_id == doc_id)):
        new_id = mapping.get(row.block_id)
        whole = row.start is None
        located: tuple[str, int | None, int | None] | None = None
        if new_id is not None:
            text = new_texts.get(new_id, "")
            if whole:
                located = (new_id, None, None)
            elif row.quote and text[row.start : row.end] == row.quote:
                located = (new_id, row.start, row.end)
            elif row.quote and (i := _nearest(text, row.quote, row.start or 0)) is not None:
                located = (new_id, i, i + len(row.quote))
        if located is None and not whole and row.quote:
            # 块切分变了（如一段拆成两段）：在全文里找唯一出现的位置
            hits = [(bid, t.find(row.quote)) for bid, t in new_texts.items() if row.quote in t]
            if len(hits) == 1:
                bid, i = hits[0]
                located = (bid, i, i + len(row.quote))
        if located is None:
            row.status = "stale"
            if new_id is not None:
                row.block_id = new_id
            stale += 1
            continue
        row.block_id, row.start, row.end = located
        if whole:
            row.quote = new_texts.get(row.block_id, row.quote)
        row.status = "ok"
    return stale
