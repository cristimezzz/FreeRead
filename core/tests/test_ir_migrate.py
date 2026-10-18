from freeread.domain.ir.migrate import BlockRef, iou, map_blocks, similarity


def ref(id, h, text="", page=0, bbox=(0, 0, 100, 20)):
    return BlockRef(id, h, text, page, bbox)


def test_exact_hash_matches_including_duplicates_in_order():
    old = [ref("b_0000", "h1"), ref("b_0001", "dup"), ref("b_0002", "dup")]
    new = [ref("b_0000", "dup"), ref("b_0001", "h1"), ref("b_0002", "dup")]
    assert map_blocks(old, new) == {"b_0000": "b_0001", "b_0001": "b_0000", "b_0002": "b_0002"}


def test_fuzzy_match_same_page_by_bbox_and_text():
    old = [ref("b_0005", "x", "Transformers use self attention.", 2, (72, 100, 300, 140))]
    new = [
        ref("b_0001", "y", "Transformers use self-attention!", 2, (70, 102, 302, 142)),
        ref("b_0002", "z", "Transformers use self-attention!", 3, (70, 102, 302, 142)),
    ]
    assert map_blocks(old, new) == {"b_0005": "b_0001"}


def test_high_similarity_matches_even_when_boxes_differ():
    text = "A long paragraph about neural machine translation with many words in it."
    old = [ref("b_0001", "x", text, 0, (0, 0, 100, 100))]
    new = [ref("b_0009", "y", text + " ", 0, (300, 500, 500, 700))]
    assert map_blocks(old, new) == {"b_0001": "b_0009"}


def test_unmatched_blocks_are_left_out_and_matching_is_one_to_one():
    old = [
        ref("b_0001", "x", "Results on WMT14 are strong.", 1, (72, 100, 300, 140)),
        ref("b_0002", "x2", "Results on WMT14 are strong!", 1, (72, 100, 300, 140)),
        ref("b_0003", "gone", "Completely different text", 1, (72, 400, 300, 440)),
        BlockRef("b_0004", "noanchor", "no anchors", None, None),
    ]
    new = [ref("b_0000", "y", "Results on WMT14 are strong.", 1, (72, 101, 300, 141))]
    mapping = map_blocks(old, new)
    assert mapping == {"b_0001": "b_0000"}  # 得分最高的那个拿走唯一的新块


def test_placeholders_and_case_are_ignored_in_similarity():
    assert similarity("Loss ⟦EQ1⟧ is small", "loss ⟦EQ2⟧ is SMALL") == 1.0
    assert similarity("", "x") == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == 1 / 3
