"""ADR-0003 跟进（M1）的 Normalizer 规则：abstract / author_info、MinerU 子图合并、
Docling 题目 / 脚注 / 参考文献。录制输出见 tests/fixtures/raw/<engine>/。"""

import json
from pathlib import Path

import pytest

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.normalize_common import RawBlock, mark_front_matter

RAW = Path(__file__).parent / "fixtures" / "raw"
SHA = "c0ffee" * 10 + "abcd"
P = BlockType.PARAGRAPH
ABSTRACT_TEXT = (
    "Document understanding systems convert page images into structured text, and we study "
    "how each stage of the pipeline contributes to the final accuracy on a synthetic benchmark. "
) * 3


def _fixture(engine: str, filename: str):
    f = RAW / engine / filename
    if not f.exists():
        pytest.skip(f"no recorded {engine} fixture")
    return json.loads(f.read_text(encoding="utf-8"))


def _front(blocks: list[RawBlock]) -> list[BlockType]:
    mark_front_matter(blocks, [(612, 792)] * 2)
    return [b.type for b in blocks]


# ---- abstract / author_info（所有 Normalizer 共用，normalize_common.mark_front_matter）


def test_recorded_fixtures_recognise_author_info_and_abstract():
    from freeread.infra.parsers.mineru import normalize_middle
    from freeread.infra.parsers.pymupdf_fast import extract, normalize_extract

    for doc, problems in (
        normalize_middle(_fixture("mineru", "middle.json"), SHA, "rec"),
        normalize_extract(extract(RAW / "synthetic.pdf"), SHA, "rec"),
    ):
        assert problems == []
        authors = [b for b in doc.blocks if b.type == BlockType.AUTHOR_INFO]
        assert [b.text for b in authors] == ["Ada Example and Bo Sample, Example University"]
        abstracts = [b for b in doc.blocks if b.type == BlockType.ABSTRACT]
        # 只有 "Abstract" 标题下的那一段是摘要，Introduction 之后仍是正文
        assert len(abstracts) == 1 and abstracts[0].text.startswith("Document understanding")
        intro = next(b for b in doc.blocks if b.text == "1 Introduction")
        assert doc.blocks[intro.order + 1].type == P


def test_recorded_docling_fixture_recognises_abstract():
    from freeread.infra.parsers.docling import normalize_docling

    # 录制的 Docling 输出把题目和作者行当成了页眉（furniture），这里只能验证摘要
    doc, problems = normalize_docling(_fixture("docling", "docling.json"), SHA, "rec")
    assert problems == []
    assert [b.type for b in doc.blocks[:3]] == [
        BlockType.HEADING,
        BlockType.ABSTRACT,
        BlockType.HEADING,
    ]


def test_front_matter_keyword_and_position_rules():
    blocks = [
        RawBlock(BlockType.TITLE, 0, (50, 60, 560, 100), text="A Study of Layout Parsing"),
        RawBlock(P, 0, (50, 110, 400, 122), text="Ada Example1,2, Bo Sample2 and Cy Third3*"),
        RawBlock(P, 0, (50, 125, 300, 135), text="Received: 12 March 2022"),
        RawBlock(
            P, 0, (50, 140, 560, 160), text="1 Department of Physics, Example University, USA"
        ),
        RawBlock(P, 0, (50, 162, 300, 170), text="* ada@example.org"),
        RawBlock(P, 0, (50, 180, 560, 300), text=ABSTRACT_TEXT),
        RawBlock(P, 0, (50, 305, 560, 315), text="Keywords: parsing; layout"),
        RawBlock(BlockType.HEADING, 0, (50, 330, 200, 342), text="1 Introduction"),
        RawBlock(P, 0, (50, 350, 300, 600), text=ABSTRACT_TEXT),
        RawBlock(P, 0, (50, 700, 560, 740), text="2 School of Arts, Other University, Germany"),
    ]
    assert _front(blocks) == [
        BlockType.TITLE,
        BlockType.AUTHOR_INFO,
        P,  # 日期跳过，不终止作者区
        BlockType.AUTHOR_INFO,
        BlockType.AUTHOR_INFO,
        BlockType.ABSTRACT,
        P,
        BlockType.HEADING,
        P,
        P,  # 页面底部的单位不属于作者区
    ]


def test_front_matter_misread_heading_author_line():
    # PyMuPDF 会把加粗的作者行判成 heading
    blocks = [
        RawBlock(BlockType.TITLE, 0, (50, 60, 560, 100), text="A Study"),
        RawBlock(BlockType.HEADING, 0, (50, 110, 400, 122), text="Ada Example, Bo Sample", level=2),
        RawBlock(BlockType.HEADING, 0, (50, 130, 200, 142), text="Introduction", level=1),
    ]
    assert _front(blocks) == [BlockType.TITLE, BlockType.AUTHOR_INFO, BlockType.HEADING]
    assert blocks[1].level is None


def test_front_matter_abstract_keyword_and_continuation():
    blocks = [
        RawBlock(P, 0, (50, 300, 290, 400), text="Abstract. The popularity of caffeine is high"),
        RawBlock(P, 0, (300, 300, 560, 400), text="in the striatum, the main receiving area."),
        RawBlock(P, 0, (50, 420, 560, 440), text="Key words. Caffeine; adenosine"),
        RawBlock(BlockType.HEADING, 1, (50, 60, 300, 75), text="摘要"),
        RawBlock(P, 1, (50, 80, 560, 200), text="强化学习已成为工程中设计任务的强大工具。"),
        RawBlock(BlockType.HEADING, 1, (50, 210, 300, 225), text="引言"),
        RawBlock(P, 1, (50, 230, 560, 400), text="正文。"),
    ]
    assert _front(blocks) == [
        BlockType.ABSTRACT,
        BlockType.ABSTRACT,  # 小写开头的同页续段
        P,
        BlockType.HEADING,
        BlockType.ABSTRACT,
        BlockType.HEADING,
        P,
    ]


def test_front_matter_is_conservative():
    # 没有 title：不猜作者区
    assert _front(
        [
            RawBlock(P, 0, (50, 110, 400, 122), text="Ada Example, Bo Sample"),
            RawBlock(P, 0, (50, 180, 560, 300), text=ABSTRACT_TEXT),
        ]
    ) == [P, P]
    # title 后第一块不像人名（如 Nature 式正文首段）：既不标作者，也不按位置标摘要
    assert _front(
        [
            RawBlock(BlockType.TITLE, 0, (50, 60, 560, 100), text="A Study"),
            RawBlock(P, 0, (50, 180, 560, 300), text=ABSTRACT_TEXT),
        ]
    ) == [BlockType.TITLE, P]
    # 作者区之后的长段落较窄（单栏正文）且后面没有关键词行：不标摘要
    assert _front(
        [
            RawBlock(BlockType.TITLE, 0, (50, 60, 560, 100), text="A Study"),
            RawBlock(P, 0, (50, 110, 400, 122), text="Ada Example & Bo Sample"),
            RawBlock(P, 0, (50, 180, 290, 500), text=ABSTRACT_TEXT),
        ]
    ) == [BlockType.TITLE, BlockType.AUTHOR_INFO, P]
    # 同样较窄，但紧跟 "a | b | c" 关键词行（PNAS）：是摘要
    assert _front(
        [
            RawBlock(BlockType.TITLE, 0, (50, 60, 560, 100), text="A Study"),
            RawBlock(P, 0, (50, 110, 400, 122), text="Ada Example & Bo Sample"),
            RawBlock(P, 0, (50, 180, 290, 500), text=ABSTRACT_TEXT),
            RawBlock(P, 0, (50, 505, 290, 515), text="parsing | layout | reading order"),
        ]
    ) == [BlockType.TITLE, BlockType.AUTHOR_INFO, BlockType.ABSTRACT, P]


# ---- MinerU：同一图注之上的子图合并、子图标号过滤


def _subfigure_middle(right_x0: float, with_caption: bool = True) -> dict:
    """在录制的 MinerU 输出里把那张 chart 换成"两个子图 + 子图标号 + 一个图注"。"""
    middle = _fixture("mineru", "middle.json")
    blocks = middle["pages"][0]["blocks"]
    i = next(k for k, b in enumerate(blocks) if b["type"] == "chart")
    caption = blocks[i]["content"][1] | {"type": "image_caption"}

    def label(x0: float, text: str) -> dict:
        return {
            "type": "image_caption",
            "bbox": [x0, 0.286, x0 + 0.013, 0.30],
            "content": [{"type": "text", "content": text}],
        }

    def image(x0: float, x1: float, extra: list[dict]) -> dict:
        body = {"type": "image_body", "bbox": [x0, 0.286, x1, 0.478], "image_path": "sub.jpg"}
        return {"type": "image", "bbox": [x0, 0.286, x1, 0.478], "content": [body, *extra]}

    right = [label(right_x0, "(b)")] + ([caption] if with_caption else [])
    blocks[i : i + 1] = [image(0.507, 0.68, [label(0.507, "a")]), image(right_x0, 0.884, right)]
    return middle


def test_mineru_merges_subfigures_above_one_caption():
    from freeread.infra.parsers.mineru import normalize_middle

    doc, problems = normalize_middle(_subfigure_middle(0.69), SHA, "rec")
    assert problems == []
    figs = [b for b in doc.blocks if b.type == BlockType.FIGURE]
    assert len(figs) == 1 and len(doc.assets) == 2  # 一张图 + 一张表
    x0, _, x1, _ = figs[0].anchors[0].bbox
    assert x0 < 0.51 * 612 and x1 > 0.88 * 612  # 并集覆盖两个子图
    captions = [b for b in doc.blocks if b.type == BlockType.CAPTION]
    assert not any(c.text in ("a", "(b)") for c in captions)  # 子图标号被丢弃
    cap = next(c for c in captions if c.label == "Figure 1")
    assert cap.caption_of == figs[0].id
    assert doc.blocks[cap.order - 1].id == figs[0].id  # 整图紧挨在图注之前


def test_mineru_keeps_figures_apart_when_distant_or_without_caption():
    from freeread.infra.parsers.mineru import normalize_middle

    # 两图相距 > 20pt：不是同一张图
    doc, _ = normalize_middle(_subfigure_middle(0.75), SHA, "rec")
    assert sum(b.type == BlockType.FIGURE for b in doc.blocks) == 2
    # 下方没有 "Figure N" 图注：不合并，但子图标号照样丢弃
    doc, _ = normalize_middle(_subfigure_middle(0.69, with_caption=False), SHA, "rec")
    assert sum(b.type == BlockType.FIGURE for b in doc.blocks) == 2
    assert not any(b.type == BlockType.CAPTION and b.text in ("a", "(b)") for b in doc.blocks)


def test_merge_subfigures_refuses_to_swallow_body_text():
    from freeread.infra.parsers.mineru import merge_subfigures

    blocks = [
        RawBlock(BlockType.FIGURE, 0, (50, 50, 290, 200)),
        RawBlock(P, 0, (50, 205, 290, 260), text="A paragraph that sits between two figures. " * 2),
        RawBlock(BlockType.FIGURE, 0, (50, 215, 560, 400)),
        RawBlock(BlockType.CAPTION, 0, (50, 405, 560, 430), text="Figure 2. Two panels."),
    ]
    assert [b.type for b in merge_subfigures(blocks)] == [
        BlockType.FIGURE,
        P,
        BlockType.FIGURE,
        BlockType.CAPTION,
    ]


def test_merge_subfigures_two_groups_sharing_one_caption_keep_all_panels():
    """左右两组子图相距超过 SUBFIG_GAP、共用一个图注：合并成一张图，不丢任何一组。"""
    from freeread.infra.parsers.mineru import merge_subfigures

    blocks = [
        RawBlock(BlockType.FIGURE, 0, (50, 50, 150, 200)),
        RawBlock(BlockType.FIGURE, 0, (160, 50, 260, 200)),
        RawBlock(BlockType.FIGURE, 0, (320, 50, 420, 200)),
        RawBlock(BlockType.FIGURE, 0, (430, 50, 530, 200)),
        RawBlock(BlockType.CAPTION, 0, (50, 205, 530, 230), text="Figure 3. Four panels."),
    ]
    out = merge_subfigures(blocks)
    assert [b.type for b in out] == [BlockType.FIGURE, BlockType.CAPTION]
    assert out[0].bbox == (50, 50, 530, 200)


# ---- Docling：title / footnote / reference_entry 的位置与关键词规则


def _docling_doc(items: list[tuple]) -> dict:
    """最小的 DoclingDocument：items 为 (label, text, 左上原点 bbox[, 额外字段])，全在第 1 页。"""
    h = 792
    texts = []
    for i, (label, text, (x0, y0, x1, y1), *extra) in enumerate(items):
        bbox = {"l": x0, "t": h - y0, "r": x1, "b": h - y1, "coord_origin": "BOTTOMLEFT"}
        texts.append(
            {
                "self_ref": f"#/texts/{i}",
                "label": label,
                "text": text,
                "content_layer": "body",
                "children": [],
                "prov": [{"page_no": 1, "bbox": bbox}],
                **(extra[0] if extra else {}),
            }
        )
    return {
        "pages": {"1": {"size": {"width": 612, "height": h}}},
        "texts": texts,
        "body": {"children": [{"$ref": t["self_ref"]} for t in texts]},
    }


def test_docling_title_footnote_and_reference_rules():
    from freeread.infra.parsers.docling import normalize_docling

    ref = "Example, A. & Sample, B. Parsing pages at scale. J. Doc. 12, 1–10 (2020)."
    data = _docling_doc(
        [
            ("section_header", "Article", (40, 28, 86, 40)),
            ("section_header", "A Study of Layout Parsing at Scale", (40, 50, 500, 100)),
            ("text", "Ada Example1, Bo Sample2", (40, 110, 400, 122)),
            ("text", "Received: 12 March 2022", (40, 130, 140, 140)),
            ("text", ABSTRACT_TEXT, (40, 150, 560, 300)),
            ("section_header", "Introduction", (40, 320, 120, 332)),
            ("text", "Body text. " * 20, (40, 340, 290, 500)),
            ("list_item", "First we prepare the samples", (40, 505, 290, 515), {"marker": "1."}),
            ("list_item", "Then we measure them", (40, 517, 290, 527), {"marker": "2."}),
            ("list_item", ref, (300, 340, 560, 360), {"marker": "1."}),
            (
                "list_item",
                ref.replace("Example, A.", "Sample, B."),
                (300, 362, 560, 382),
                {"marker": "2."},
            ),
            ("list_item", ref.replace("2020", "2021"), (300, 384, 560, 404), {"marker": "3."}),
            (
                "text",
                "1Department of Physics, Example University, USA. 2School of Arts",
                (40, 700, 560, 730),
            ),
            ("text", "*Corresponding author. Email: ada@example.org", (40, 735, 300, 745)),
        ]
    )
    doc, problems = normalize_docling(data, SHA, "t")
    assert problems == []
    assert [b.type for b in doc.blocks] == [
        BlockType.HEADING,  # "Article" 栏目名不是题目
        BlockType.TITLE,
        BlockType.AUTHOR_INFO,
        BlockType.FOOTNOTE,
        BlockType.ABSTRACT,
        BlockType.HEADING,
        P,
        BlockType.LIST_ITEM,  # 正文里的编号步骤不是参考文献
        BlockType.LIST_ITEM,
        BlockType.REFERENCE_ENTRY,
        BlockType.REFERENCE_ENTRY,
        BlockType.REFERENCE_ENTRY,
        BlockType.FOOTNOTE,
        BlockType.FOOTNOTE,
    ]
    assert doc.meta.title == "A Study of Layout Parsing at Scale"
    refs = [b for b in doc.blocks if b.type == BlockType.REFERENCE_ENTRY]
    assert refs[0].text.startswith("1. Example, A.")  # Docling 的 marker 补回正文
    assert [r.id for r in doc.references] == ["r_1", "r_2", "r_3"]


def test_docling_keeps_engine_title_and_body_affiliation_mentions():
    from freeread.infra.parsers.docling import normalize_docling

    data = _docling_doc(
        [
            ("title", "A Study of Layout Parsing", (40, 50, 500, 100)),
            ("section_header", "Results From Three Large Groups", (40, 110, 500, 160)),
            # 首页上半部分提到大学的正文：不是脚注
            (
                "text",
                "1 University hospitals were sampled in 2019 across " * 5,
                (40, 300, 560, 400),
            ),
        ]
    )
    doc, _ = normalize_docling(data, SHA, "t")
    assert [b.type for b in doc.blocks] == [BlockType.TITLE, BlockType.HEADING, P]


def test_normalizer_versions_bumped():
    from freeread.infra.parsers.docling import DoclingNormalizer
    from freeread.infra.parsers.marker import MarkerNormalizer
    from freeread.infra.parsers.mineru import MinerUNormalizer
    from freeread.infra.parsers.normalize_common import NORMALIZER_VERSION
    from freeread.infra.parsers.pymupdf_fast import PyMuPDFFastNormalizer

    # 规则变了就要升版本，解析任务据此用已有 raw 重新规范化（services/parse.py）
    assert NORMALIZER_VERSION == "0.2.0"
    for n in (DoclingNormalizer, MarkerNormalizer, MinerUNormalizer, PyMuPDFFastNormalizer):
        assert n.version == "0.2.0"
