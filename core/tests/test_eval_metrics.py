from freeread.eval.metrics import (
    PB,
    iou,
    kendall_tau,
    match,
    normalize_latex,
    score_document,
    score_page,
)


def test_iou_and_match():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9
    gold = [PB(0, (0, 0, 10, 10), "paragraph", 0), PB(0, (0, 20, 10, 30), "paragraph", 1)]
    pred = [PB(0, (0, 21, 10, 31), "paragraph", 0), PB(0, (0, 1, 10, 11), "heading", 1)]
    assert sorted(match(gold, pred)) == [(0, 1), (1, 0)]


def test_kendall_tau():
    assert kendall_tau([0, 1, 2, 3]) == (1.0, 6)
    assert kendall_tau([3, 2, 1, 0]) == (-1.0, 6)
    assert kendall_tau([5]) == (0.0, 0)


def test_score_page_counts_types_order_and_text():
    gold = [
        PB(0, (0, 0, 100, 10), "heading", 0, text="Introduction"),
        PB(0, (0, 20, 100, 60), "paragraph", 1, text="Hello world"),
        PB(0, (0, 70, 100, 90), "equation", 2, latex=r"\left( a+b \right)"),
    ]
    pred = [
        PB(0, (0, 70, 100, 90), "equation", 0, latex="(a + b)"),  # 顺序错
        PB(0, (0, 0, 100, 10), "paragraph", 1, text="Introduction"),  # 类型错（粗粒度也错）
        PB(0, (0, 20, 100, 60), "paragraph", 2, text="Hello world"),
        PB(0, (200, 200, 300, 300), "figure", 3),  # 多检
    ]
    s = score_page(gold, pred).summary()
    assert s["det_precision"] == 0.75 and s["det_recall"] == 1.0
    assert s["type_acc"] == round(2 / 3, 4)
    assert s["reading_order_tau"] == round(-1 / 3, 4)
    assert s["latex_ned"] == 0.0
    assert s["equation_recall"] == 1.0
    assert s["text_ned"] == 0.0


def test_score_document_only_uses_golden_pages():
    gold = {1: [PB(1, (0, 0, 10, 10), "paragraph", 0, text="x")]}
    pred = [
        PB(0, (0, 0, 10, 10), "paragraph", 0, text="x"),
        PB(1, (0, 0, 10, 10), "paragraph", 1, text="x"),
    ]
    s = score_document(gold, pred).summary()
    assert s["n_pred"] == 1 and s["det_f1"] == 1.0


def test_normalize_latex():
    assert normalize_latex(r"\mathrm{BM} = 2 . 2 \left( x \right)") == normalize_latex("BM=2.2(x)")
