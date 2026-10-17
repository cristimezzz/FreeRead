"""Normalizer 单测：用合成 PDF（tests/fixtures/raw/synthetic.pdf，由 scripts/m0_make_synthetic_pdf.py 生成）
以及各引擎在该 PDF 上录制的原生输出（tests/fixtures/raw/<engine>/）。"""

import json
from pathlib import Path

import pytest

from freeread.domain.ir.models import BlockType, validate_document
from freeread.infra.parsers.normalize_common import RawBlock, build_document, merge_continuations

RAW = Path(__file__).parent / "fixtures" / "raw"
SHA = "c0ffee" * 10 + "abcd"


def test_build_document_assigns_ids_sections_captions_refs():
    blocks = [
        RawBlock(BlockType.TITLE, 0, (72, 60, 540, 90), text="A Title"),
        RawBlock(BlockType.HEADING, 0, (72, 100, 300, 115), text="1 Introduction", level=1),
        RawBlock(
            BlockType.PARAGRAPH,
            0,
            (72, 120, 300, 200),
            segments=[("text", "Loss is "), ("math", r"\alpha+\beta"), ("text", ".")],
        ),
        RawBlock(BlockType.FIGURE, 0, (320, 100, 540, 250)),
        RawBlock(BlockType.CAPTION, 0, (320, 255, 540, 270), text="Figure 1. A plot."),
        RawBlock(BlockType.HEADING, 1, (72, 60, 300, 75), text="References", level=1),
        RawBlock(BlockType.PARAGRAPH, 1, (72, 80, 540, 95), text="1. Doe, J. A paper (2020)."),
    ]
    doc, problems = build_document(
        blocks, pdf_sha256=SHA, pages=[(612, 792)] * 2, engine="t", engine_version="0"
    )
    assert problems == []
    assert [b.id for b in doc.blocks][:3] == ["b_0000", "b_0001", "b_0002"]
    para = doc.blocks[2]
    assert para.text == "Loss is ⟦EQ1⟧." and para.inlines[0].latex == r"\alpha+\beta"
    assert para.section_id == "s_1"
    cap = doc.blocks[4]
    assert cap.label == "Figure 1" and cap.caption_of == doc.blocks[3].id
    assert doc.blocks[3].asset_id == doc.assets[0].id
    assert doc.blocks[6].type == BlockType.REFERENCE_ENTRY
    assert doc.references[0].id == "r_1"
    assert doc.meta.title == "A Title" and doc.meta.language == "en"
    assert validate_document(doc) == []


def test_sanitize_table_html():
    from freeread.infra.parsers.normalize_common import sanitize_table_html

    html = '<table class="x"><tr><td colspan="2" style="a"><span>a</span><math>x^2</math></td></tr><script>bad()</script></table>'
    assert (
        sanitize_table_html(html)
        == '<table><tr><td colspan="2">a<math>x^2</math></td></tr>bad()</table>'
    )


def test_merge_continuations_adds_anchor():
    a = RawBlock(BlockType.PARAGRAPH, 0, (72, 700, 300, 760), text="first half")
    b = RawBlock(BlockType.PARAGRAPH, 1, (72, 60, 300, 100), text="second half")
    merged = merge_continuations([a, b], [False, True])
    assert len(merged) == 1 and merged[0].text == "first half second half"
    assert merged[0].extra_anchors == [(1, (72, 60, 300, 100))]


def test_pymupdf_fast_on_synthetic_pdf():
    from freeread.infra.parsers.pymupdf_fast import extract, normalize_extract

    doc, problems = normalize_extract(extract(RAW / "synthetic.pdf"), SHA, "test")
    assert problems == []
    types = [b.type for b in doc.blocks]
    assert types[0] == BlockType.TITLE
    headings = [b.text for b in doc.blocks if b.type == BlockType.HEADING]
    assert "1 Introduction" in headings and "References" in headings
    assert sum(t == BlockType.REFERENCE_ENTRY for t in types) == 3
    assert any(b.type == BlockType.CAPTION and b.label == "Figure 1" for b in doc.blocks)
    # 双栏：左栏 "2 Method" 应排在右栏图注之前
    order = {b.text: b.order for b in doc.blocks}
    fig_cap = next(b.order for b in doc.blocks if b.label == "Figure 1")
    assert order["2 Method"] < fig_cap


def _engine_fixture(engine: str, filename: str):
    f = RAW / engine / filename
    if not f.exists():
        pytest.skip(f"no recorded {engine} fixture")
    return json.loads(f.read_text(encoding="utf-8"))


def _assert_reasonable(doc, problems):
    assert problems == []
    assert validate_document(doc) == []
    types = {b.type for b in doc.blocks}
    assert BlockType.PARAGRAPH in types
    assert doc.source.page_count == 2
    text = " ".join(b.text for b in doc.blocks)
    assert "Introduction" in text and "Conclusion" in text


def test_mineru_normalizer_on_recorded_output():
    from freeread.infra.parsers.mineru import normalize_middle

    _assert_reasonable(*normalize_middle(_engine_fixture("mineru", "middle.json"), SHA, "rec"))


def test_docling_normalizer_on_recorded_output():
    from freeread.infra.parsers.docling import normalize_docling

    _assert_reasonable(*normalize_docling(_engine_fixture("docling", "docling.json"), SHA, "rec"))
