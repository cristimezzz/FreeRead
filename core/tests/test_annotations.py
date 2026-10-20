import pytest

from freeread.infra.db.models import AnnotationRow, BlockRow, QANodeRow, QASessionRow
from freeread.infra.llm.fake import FakeProvider
from freeread.services.annotations import (
    AnnotationError,
    AnnotationIn,
    AnnotationPatch,
    migrate_annotations,
)
from freeread.services.export import ExportOptions, _highlight, _inline_md
from tests.test_translate import configure, parsed_doc, zh


async def first_para(ctx, tmp_path):
    doc_id, _, ordered = await parsed_doc(ctx, tmp_path)
    bid, _, text = next(b for b in ordered if b[1] == "paragraph" and len(b[2]) > 40)
    return doc_id, bid, text, ordered


async def test_crud_and_order(ctx, tmp_path):
    doc_id, bid, text, ordered = await first_para(ctx, tmp_path)
    svc = ctx.annotations
    later = next(b for b, t, _ in reversed(ordered) if t == "paragraph")

    a = svc.create(doc_id, AnnotationIn(block_id=later, color="green"))
    assert a.start is None and a.quote and a.status == "ok"
    b = svc.create(doc_id, AnnotationIn(block_id=bid, start=5, end=15, note="要点"))
    assert b.quote == text[5:15] and b.color == "yellow"
    assert [x.id for x in svc.list_for_doc(doc_id)] == [b.id, a.id]  # 阅读顺序

    with pytest.raises(AnnotationError):
        svc.create(doc_id, AnnotationIn(block_id=bid, start=5, end=len(text) + 1))
    with pytest.raises(AnnotationError):
        svc.create(doc_id, AnnotationIn(block_id=bid, start=5))
    with pytest.raises(AnnotationError):
        svc.create(doc_id, AnnotationIn(block_id="b_9999"))
    with pytest.raises(LookupError):
        svc.create("d_nope", AnnotationIn(block_id=bid))

    assert svc.update(b.id, AnnotationPatch(color="pink", note="改")).note == "改"
    assert svc.delete(b.id) and not svc.delete(b.id)


def test_migrate_relocates_by_quote(ctx):
    rows = [
        AnnotationRow(id="a1", doc_id="d", block_id="b_0001", start=4, end=9, quote="quick"),
        AnnotationRow(id="a2", doc_id="d", block_id="b_0002", start=0, end=5, quote="hello"),
        AnnotationRow(id="a3", doc_id="d", block_id="b_0003", start=0, end=3, quote="zzz"),
        AnnotationRow(id="a4", doc_id="d", block_id="b_0004", start=None, end=None, quote="old"),
        AnnotationRow(id="a5", doc_id="d", block_id="b_0005", start=0, end=4, quote="gone"),
    ]

    class S:
        def scalars(self, _q):
            return rows

    mapping = {"b_0001": "b_0101", "b_0002": "b_0102", "b_0004": "b_0104", "b_0005": "b_0105"}
    texts = {
        "b_0101": "The quick fox",  # 原位置仍是 quick
        "b_0102": "Well, hello there",  # 文本变了：按 quote 重新定位
        "b_0103": "x zzz y",  # 未映射，但全文里唯一出现
        "b_0104": "new whole block",
        "b_0105": "nothing here",
    }
    stale = migrate_annotations(S(), "d", mapping, texts)
    by = {r.id: r for r in rows}
    assert (by["a1"].block_id, by["a1"].start, by["a1"].end) == ("b_0101", 4, 9)
    assert (by["a2"].block_id, by["a2"].start, by["a2"].end) == ("b_0102", 6, 11)
    assert (by["a3"].block_id, by["a3"].start) == ("b_0103", 2)
    assert by["a4"].block_id == "b_0104" and by["a4"].quote == "new whole block"
    assert by["a5"].status == "stale" and by["a5"].block_id == "b_0105"
    assert stale == 1


async def test_reparse_keeps_annotations(ctx, tmp_path):
    doc_id, bid, text, _ = await first_para(ctx, tmp_path)
    a = ctx.annotations.create(doc_id, AnnotationIn(block_id=bid, start=0, end=10))

    async def noop(*_):
        pass

    await ctx.parse.run(doc_id, "pymupdf", noop, force=True)
    [after] = ctx.annotations.list_for_doc(doc_id)
    assert after.id == a.id and after.status == "ok" and after.quote == text[:10]
    with ctx.sessions() as s:
        assert (
            s.get(BlockRow, (doc_id, after.block_id)).text[after.start : after.end] == after.quote
        )


def test_highlight_and_inline_md():
    assert _highlight("abc def ghi", [(4, 7)]) == "abc ==def== ghi"
    assert _highlight("abc def ghi", [(3, 8), (6, 11)]) == "abc ==def ghi=="  # 合并、去掉首尾空白
    assert _highlight("x ⟦EQ1⟧ y", [(3, 5)]) == "x ⟦EQ1⟧ y"  # 落在占位符中间
    inl = [{"key": "EQ1", "kind": "math", "latex": " x^2 "}, {"key": "C1", "kind": "cite"}]
    assert _inline_md("a ⟦EQ1⟧ b⟦C1⟧", inl) == "a $x^2$ b"


async def test_export_markdown(ctx, tmp_path):
    configure(ctx, FakeProvider("p1", responder=zh))
    doc_id, bid, text, _ = await first_para(ctx, tmp_path)
    _ = [e async for e in ctx.translate.translate_blocks(doc_id, [bid])]
    ctx.annotations.create(
        doc_id, AnnotationIn(block_id=bid, start=0, end=10, note="第一行\n第二行")
    )
    with ctx.sessions.begin() as s:
        sess = QASessionRow(doc_id=doc_id, scope=f"doc:{doc_id}", title="试问")
        s.add(sess)
        s.flush()
        s.add(
            QANodeRow(
                session_id=sess.id,
                question="讲了什么？",
                answer=f"讲了排版 [{bid}]。",
                citations=[bid],
                stats={},
                model="m",
                prompt_version="qa_answer@1",
                status="ok",
            )
        )

    md = ctx.export.markdown(doc_id, ExportOptions(qa=True))
    assert md.startswith("# ")
    assert "## 批注" in md and f"- =={text[:10].strip()}== [p. 1]" in md
    assert "  第一行\n  第二行" in md
    assert "## 正文" in md and f"=={text[:10].strip()}==" in md
    assert "> 译：" in md  # 译文放在原文下面
    assert "**批注**：第一行" in md
    assert "## 问答" in md and "讲了排版 [p. 1]。" in md
    assert "⟦" not in md

    only = ctx.export.markdown(
        doc_id, ExportOptions(translation="only", annotations=False, summary=False)
    )
    assert "## 批注" not in only and "\n译：" in only and "> 译：" not in only
    bare = ctx.export.markdown(doc_id, ExportOptions(body=False, annotations=False))
    assert "## 正文" not in bare


def test_annotations_and_export_api(client, tmp_path):
    ctx = client.app.state.ctx
    doc_id, bid, _, _ = client.portal.call(first_para, ctx, tmp_path)
    base = f"/documents/{doc_id}/annotations"

    r = client.post(base, json={"block_id": bid, "start": 0, "end": 10, "color": "blue"})
    assert r.status_code == 201
    ann = r.json()
    assert client.post(base, json={"block_id": "b_9999"}).status_code == 422
    assert client.post(base, json={"block_id": bid, "color": "red"}).status_code == 422
    assert client.post("/documents/nope/annotations", json={"block_id": bid}).status_code == 404
    assert [a["id"] for a in client.get(base).json()] == [ann["id"]]

    r = client.patch(f"/annotations/{ann['id']}", json={"note": "好"})
    assert r.status_code == 200 and r.json()["note"] == "好"
    assert client.patch("/annotations/nope", json={"note": "x"}).status_code == 404

    r = client.get(f"/documents/{doc_id}/export/markdown", params={"translation": "off"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "**批注**：好" in r.text
    assert client.get("/documents/nope/export/markdown").status_code == 404

    out = tmp_path / "out.md"
    r = client.post(f"/documents/{doc_id}/export/markdown", json={"path": str(out), "qa": True})
    assert r.status_code == 200 and out.read_text(encoding="utf-8").startswith("# ")
    assert r.json()["bytes"] == out.stat().st_size
    r = client.post(f"/documents/{doc_id}/export/markdown", json={"path": "relative.md"})
    assert r.status_code == 422

    assert client.delete(f"/annotations/{ann['id']}").status_code == 204
    assert client.delete(f"/annotations/{ann['id']}").status_code == 404
