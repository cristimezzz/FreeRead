from freeread.domain.ir.models import (
    Anchor,
    Block,
    BlockType,
    Document,
    Inline,
    InlineKind,
    PageInfo,
    ParserInfo,
    Source,
    doc_id_from_sha256,
    validate_document,
)

SHA = "3f9a1c2b7e4d5a60" + "0" * 48


def make_doc(blocks: list[Block]) -> Document:
    return Document(
        doc_id=doc_id_from_sha256(SHA),
        source=Source(pdf_sha256=SHA, page_count=1, pages=[PageInfo(index=0, width=612, height=792)]),
        parser=ParserInfo(
            engine="test", engine_version="0", normalizer_version="0", created_at="2026-10-17T00:00:00Z"
        ),
        blocks=blocks,
    )


def test_valid_document_has_no_problems():
    doc = make_doc(
        [
            Block(
                id="b_0000",
                type=BlockType.PARAGRAPH,
                order=0,
                text="Loss is ⟦EQ1⟧.",
                inlines=[Inline(key="EQ1", kind=InlineKind.MATH, latex="L")],
                anchors=[Anchor(page=0, bbox=(72, 100, 540, 140))],
                content_hash="sha256:x",
            )
        ]
    )
    assert validate_document(doc) == []


def test_detects_placeholder_mismatch_and_bad_anchor():
    doc = make_doc(
        [
            Block(
                id="b_0000",
                type=BlockType.PARAGRAPH,
                order=0,
                text="Loss is ⟦EQ1⟧.",
                anchors=[Anchor(page=3, bbox=(0, 0, 1, 1))],
                content_hash="sha256:x",
            ),
            Block(id="b_0001", type=BlockType.EQUATION, order=1, content_hash="sha256:y"),
        ]
    )
    problems = validate_document(doc)
    assert any("placeholder mismatch" in p for p in problems)
    assert any("out of range" in p for p in problems)
    assert any("equation without latex" in p for p in problems)
