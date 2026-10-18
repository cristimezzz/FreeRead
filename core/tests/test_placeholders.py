import pytest

from freeread.domain.translate.placeholders import (
    PlaceholderMismatch,
    check,
    normalize_variants,
    protect,
    restore,
)


def test_protect_citations_urls_code_and_keep_ir_placeholders():
    p = protect("Loss ⟦EQ1⟧ follows [3, 5–7] (see https://x.org/a?b=1). Run `make all`.")
    assert p.text == "Loss ⟦EQ1⟧ follows ⟦CITE1⟧ (see ⟦URL1⟧). Run ⟦CODE1⟧."
    assert p.originals == {
        "CITE1": "[3, 5–7]",
        "URL1": "https://x.org/a?b=1",
        "CODE1": "`make all`",
    }
    assert p.keys == ["EQ1", "CITE1", "URL1", "CODE1"]


def test_author_year_citations_are_translated_not_protected():
    p = protect("As shown by Smith et al. (2020), it works [12].")
    assert p.text == "As shown by Smith et al. (2020), it works ⟦CITE1⟧."


def test_restore_puts_back_only_own_placeholders_and_allows_reordering():
    p = protect("A [1] and B [2] use ⟦EQ1⟧.")
    translated = "B ⟦CITE2⟧ 和 A ⟦CITE1⟧ 都使用 ⟦EQ1⟧。"
    assert restore(p, translated) == "B [2] 和 A [1] 都使用 ⟦EQ1⟧。"


@pytest.mark.parametrize("variant", ["⟦ CITE1 ⟧", "[[CITE1]]", "【CITE1】", "〚CITE1〛", "⟦CITE1⟧"])
def test_model_variants_are_normalized(variant):
    p = protect("See [1].")
    assert restore(p, f"见 {variant}。") == "见 [1]。"
    assert normalize_variants(f"x {variant}") == "x ⟦CITE1⟧"


def test_mismatch_reports_missing_and_extra():
    p = protect("A ⟦EQ1⟧ and [4].")
    with pytest.raises(PlaceholderMismatch) as e:
        check(p, "A 和 ⟦CITE1⟧ ⟦CITE1⟧ ⟦EQ2⟧。")
    assert e.value.missing == ["EQ1"] and e.value.extra == ["CITE1", "EQ2"]


def test_text_without_placeholders_roundtrips():
    p = protect("Plain sentence.")
    assert p.keys == [] and restore(p, "普通句子。") == "普通句子。"
    with pytest.raises(PlaceholderMismatch):
        restore(p, "多了 ⟦CITE1⟧")
