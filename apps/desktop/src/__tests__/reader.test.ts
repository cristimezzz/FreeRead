import { describe, expect, it } from "vitest";
import type { Block } from "../api/ir";
import { createSseParser, type SseEvent } from "../api/sse";
import { buildTree } from "../features/library/CollectionTree";
import { formatAuthors } from "../features/library/ItemList";
import { blockAt, buildPageIndex } from "../features/reader/locate";
import { renderTableHtml, splitPlaceholders } from "../features/reader/render";
import { themeVars } from "../app/theme";

const block = (id: string, page: number, bbox: [number, number, number, number], extra: Partial<Block> = {}): Block => ({
  id,
  type: "paragraph",
  order: 0,
  text: "",
  anchors: [{ page, bbox }],
  ...extra,
});

describe("SSE parser", () => {
  it("splits events across chunk boundaries, ignores comments, parses JSON", () => {
    const events: SseEvent[] = [];
    const feed = createSseParser((e) => events.push(e));
    feed('event: ready\ndata: {}\n\n: ping\n\nevent: translation\ndata: {"block_id":"b_0001",');
    expect(events).toEqual([{ event: "ready", data: {} }]);
    feed('"text":"译文"}\r\n\r\nevent: done\ndata: {}\n\n');
    expect(events.map((e) => e.event)).toEqual(["ready", "translation", "done"]);
    expect(events[1].data).toEqual({ block_id: "b_0001", text: "译文" });
  });
});

describe("locate", () => {
  const blocks = [
    block("b_0000", 0, [72, 72, 540, 120]),
    block("b_0001", 0, [300, 200, 540, 400], { type: "figure" }),
    block("b_0002", 0, [300, 380, 540, 400], { type: "caption" }), // 压在图上的图注
    { ...block("b_0003", 0, [72, 600, 290, 760]), anchors: [{ page: 0, bbox: [72, 600, 290, 760] as [number, number, number, number] }, { page: 1, bbox: [72, 60, 290, 100] as [number, number, number, number] }] },
  ];
  const index = buildPageIndex(blocks);

  it("prefers the smallest containing block", () => {
    expect(blockAt(index, 0, 400, 390)).toBe("b_0002");
    expect(blockAt(index, 0, 400, 300)).toBe("b_0001");
  });

  it("falls back to the nearest block within tolerance, and indexes every anchor", () => {
    expect(blockAt(index, 0, 100, 125)).toBe("b_0000");
    expect(blockAt(index, 0, 100, 160)).toBeNull();
    expect(blockAt(index, 1, 100, 80)).toBe("b_0003");
    expect(blockAt(index, 5, 0, 0)).toBeNull();
  });
});

describe("render", () => {
  it("maps math placeholders to latex and keeps unknown ones", () => {
    const segs = splitPlaceholders("Loss ⟦EQ1⟧ and ⟦CITE1⟧.", [{ key: "EQ1", kind: "math", latex: "\\alpha" }]);
    expect(segs).toEqual([
      { kind: "text", text: "Loss " },
      { kind: "math", latex: "\\alpha" },
      { kind: "text", text: " and " },
      { kind: "raw", key: "CITE1" },
      { kind: "text", text: "." },
    ]);
  });

  it("sanitizes table html and renders embedded math", () => {
    const html = renderTableHtml(
      '<table onclick="x()"><tr><td colspan="2" style="color:red">a<script>alert(1)</script></td><td><math>x^2</math></td></tr></table><img src=x onerror=alert(1)>',
    );
    // KaTeX 自己的输出带 style，所以只检查注入进来的东西被去掉了
    expect(html).not.toMatch(/<script|alert|onclick|onerror|color:red|<img/);
    expect(html).toContain('colspan="2"');
    expect(html).toContain("katex");
  });
});

describe("library helpers", () => {
  it("builds a sorted collection tree from the flat list", () => {
    const tree = buildTree([
      { id: "c", zotero_key: null, name: "翻译", parent_id: "a", item_count: 1 },
      { id: "a", zotero_key: null, name: "Zoology", parent_id: null, item_count: 0 },
      { id: "b", zotero_key: null, name: "Biology", parent_id: null, item_count: 2 },
    ]);
    expect(tree.map((n) => n.c.id)).toEqual(["b", "a"]);
    expect(tree[1].children.map((n) => n.c.id)).toEqual(["c"]);
  });

  it("formats authors and skips editors", () => {
    expect(
      formatAuthors([
        { first: "Ashish", last: "Vaswani", type: "author" },
        { name: "Google Brain", type: "author" },
        { first: "E", last: "Ditor", type: "editor" },
      ]),
    ).toBe("Vaswani, Ashish; Google Brain");
  });
});

describe("theme", () => {
  it("uses a fixed warm ramp and only varies the accent", () => {
    const light = themeVars("#D97757", false, "standard");
    const dark = themeVars("#D97757", true, "standard");
    expect(light["--bg"]).toBe("#FAF9F5");
    expect(dark["--bg"]).toBe("#1F1E1D");
    expect(light["--accent"]).toBe("#D97757");
    // 换强调色不影响中性色阶
    expect(themeVars("#4F74B8", false, "standard")["--ink"]).toBe(light["--ink"]);
    // 提高对比度：辅助文字与分隔线加深
    const high = themeVars("#D97757", false, "high");
    expect(high["--ink3"]).not.toBe(light["--ink3"]);
    expect(high["--line"]).not.toBe(light["--line"]);
    expect(high["--accent-ink"]).not.toBe(light["--accent-ink"]);
  });
});
