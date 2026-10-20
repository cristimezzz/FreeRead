import { describe, expect, it } from "vitest";
import type { Inline } from "../api/ir";
import { placeSegments, selectionRange, splitByMarks } from "../features/annotations/offsets";
import { safeFileName } from "../features/annotations/ExportDialog";

const inlines: Inline[] = [{ key: "EQ1", kind: "math", latex: "x^2" }];

describe("annotation offsets", () => {
  it("places segments at their offsets in the raw text, placeholders included", () => {
    const segs = placeSegments("ab ⟦EQ1⟧ cd", inlines);
    expect(segs.map((s) => [s.kind, s.start, s.end])).toEqual([
      ["text", 0, 3],
      ["math", 3, 8],
      ["text", 8, 11],
    ]);
  });

  it("splits text by marks, later marks win on overlap", () => {
    const marks = [
      { id: "a", start: 2, end: 6, color: "yellow", hasNote: false },
      { id: "b", start: 4, end: 8, color: "blue", hasNote: true },
    ];
    const pieces = splitByMarks("0123456789", 0, marks);
    expect(pieces.map((p) => [p.text, p.mark?.id ?? null])).toEqual([
      ["01", null],
      ["23", "a"],
      ["4567", "b"],
      ["89", null],
    ]);
    // 段落不从 0 开始
    expect(splitByMarks("xyz", 10, [{ id: "c", start: 11, end: 12, color: "pink", hasNote: false }]).map((p) => p.start)).toEqual([
      10, 11, 12,
    ]);
  });

  it("maps a DOM selection back to block offsets", () => {
    const root = document.createElement("article");
    root.innerHTML =
      '<div data-block-id="b_0001"><p>' +
      '<span data-off="0" data-len="3" data-kind="text">ab </span>' +
      '<span data-off="3" data-len="5" data-kind="math"><span class="katex">x²</span></span>' +
      '<span data-off="8" data-len="1" data-kind="text"> </span>' +
      '<mark data-off="9" data-len="2" data-kind="text">cd</mark>' +
      "</p>" +
      '<div class="rf-translation"><span>译文</span></div></div>' +
      '<div data-block-id="b_0002"><span data-off="0" data-len="2" data-kind="text">ef</span></div>';
    document.body.append(root);
    const [ab, math, , cd] = root.querySelectorAll("[data-off]");
    const range = document.createRange();

    range.setStart(ab.firstChild!, 1);
    range.setEnd(cd.firstChild!, 1);
    expect(selectionRange(root, range)).toEqual({ blockId: "b_0001", start: 1, end: 10 });

    // 公式里开始 → 取公式起点
    range.setStart(math.querySelector(".katex")!.firstChild!, 1);
    range.setEnd(cd.firstChild!, 2);
    expect(selectionRange(root, range)).toEqual({ blockId: "b_0001", start: 3, end: 11 });

    // 跨块、译文里的选区不接受
    range.setStart(ab.firstChild!, 0);
    range.setEnd(root.querySelector('[data-block-id="b_0002"] span')!.firstChild!, 1);
    expect(selectionRange(root, range)).toBeNull();
    const tr = root.querySelector(".rf-translation span")!;
    range.setStart(tr.firstChild!, 0);
    range.setEnd(tr.firstChild!, 1);
    expect(selectionRange(root, range)).toBeNull();
    root.remove();
  });

  it("makes safe export file names", () => {
    expect(safeFileName('A/B: "C"?')).toBe("A B C.md");
    expect(safeFileName("  ")).toBe("FreeRead 导出.md");
  });
});
