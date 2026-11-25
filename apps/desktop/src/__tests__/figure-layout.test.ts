import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { BBox, Block, Document } from "../api/ir";
import { ReflowView } from "../features/reader/ReflowView";
import { groupFigures } from "../features/reader/figureLayout";

function block(id: string, type: Block["type"], bbox: BBox, extra: Partial<Block> = {}): Block {
  return { id, type, text: "", order: 0, anchors: [{ page: 0, bbox }], ...extra };
}

const a = block("a", "figure", [50, 100, 190, 190], { asset_id: "image-a" });
const b = block("b", "figure", [210, 120, 450, 190], { asset_id: "image-b", order: 1 });
const c = block("c", "figure", [50, 220, 450, 310], { asset_id: "image-c", order: 2 });
const label = block("label", "caption", [50, 85, 60, 94], { text: "(a)" });
const caption = block("caption", "caption", [50, 320, 450, 345], { text: "Figure 1. Shared caption.", caption_of: "c" });

describe("reflow figure layout", () => {
  it("preserves uneven panels and labels across rows, including anchors of an already merged bottom row", () => {
    const [group] = groupFigures([a, b, c, label, caption]);
    expect(group.caption.id).toBe(caption.id);
    expect(group.panels.map((p) => [p.block.id, p.bbox])).toEqual(
      [a, b, c].map((p) => [p.id, p.anchors[0].bbox]),
    );
    expect(group.labels.map((p) => p.block.id)).toEqual([label.id]);
    expect(group.bbox).toEqual([50, 85, 450, 310]);
  });

  it("handles captions above panels and leaves unconfirmed and already combined figures alone", () => {
    const above = block("above", "caption", [50, 70, 450, 90], { text: "图 1", caption_of: "a" });
    expect(groupFigures([above, a, b])[0].captionAbove).toBe(true);
    expect(groupFigures([a, b])).toEqual([]);
    expect(groupFigures([c, caption])).toEqual([]);
    expect(groupFigures([above, a, { ...b, anchors: [{ page: 1, bbox: b.anchors[0].bbox }] }])).toEqual([]);
  });

  it("keeps separately captioned and conflicting figures apart and avoids clipping body text", () => {
    const above = block("above", "caption", [50, 70, 450, 90], { text: "Figure 2", caption_of: "a" });
    const below = block("below", "caption", [50, 200, 450, 215], { text: "Figure 3", caption_of: "b" });
    expect(groupFigures([above, a, b, below])).toEqual([]);
    const right = block("right", "figure", [470, 100, 570, 190], { asset_id: "image-right" });
    const rightCaption = block("right-caption", "caption", [210, 200, 570, 215], { text: "Figure 4", caption_of: "right" });
    expect(groupFigures([above, a, b, right, rightCaption])).toEqual([]);
    const paragraph = block("body", "paragraph", [192, 130, 208, 150], { text: "Body text" });
    expect(groupFigures([a, paragraph, b, c, caption])).toEqual([]);
  });

  it.each([false, true])("renders stable panel targets and handles a crop failure of %s", async (failed) => {
    let prefetch: IntersectionObserverCallback | undefined;
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback;
      }
      callback: IntersectionObserverCallback;
      observe(target: Element) {
        if (target.matches(".rf-figure-group")) prefetch = this.callback;
      }
      disconnect() {}
    });
    const revoke = vi.fn();
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:figure");
      static revokeObjectURL = revoke;
    });
    const fetch = vi.spyOn(client, "rawFetch").mockImplementation(async (path) => {
      if (failed && path.includes("figure-crop")) throw new Error("PDF missing");
      return new Response(new Blob(["image"], { type: "image/png" }));
    });

    const doc: Document = {
      schema_version: "0.1.0", doc_id: "d_example", meta: {},
      source: { pdf_sha256: "", page_count: 1, pages: [{ index: 0, width: 500, height: 700 }] },
      parser: { engine: "mineru", engine_version: "1", created_at: "old" },
      blocks: [a, b, c, label, caption],
      assets: [a, b, c].map((p) => ({ id: p.asset_id!, path: `assets/${p.id}.png` })),
    };
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const onLocate = vi.fn();
    const props = { doc, mode: "off" as const, translations: {}, located: null, scrollKey: 0, fontSize: 17,
      onLocate, onVisible: vi.fn() };
    let signal: AbortSignal | null | undefined;
    try {
      await act(() => root.render(createElement(ReflowView, props)));
      const figure = container.querySelector<HTMLElement>("figure")!;
      const panel = figure.querySelector<HTMLButtonElement>("[data-block-id=b]")!;
      expect(container.querySelectorAll("figure")).toHaveLength(1);
      expect(container.querySelectorAll(".rf-caption")).toHaveLength(1);
      expect(figure.nextElementSibling?.textContent).toBe(caption.text);
      expect(panel.style.left).toBe("40%");
      expect(panel.style.width).toBe("60%");
      expect(fetch).not.toHaveBeenCalled();
      panel.click();
      expect(onLocate).toHaveBeenCalledWith(b);

      const scrollIntoView = vi.fn();
      panel.scrollIntoView = scrollIntoView;
      await act(() => root.render(createElement(ReflowView, { ...props, located: b.id, scrollKey: 1 })));
      expect(scrollIntoView).toHaveBeenCalled();
      expect(panel.classList.contains("located")).toBe(true);

      await act(async () => prefetch!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
      expect(fetch.mock.calls[0][0]).toBe("/documents/d_example/figure-crop?page=0&x0=50&y0=85&x1=450&y1=310");
      signal = fetch.mock.calls[0][1]?.signal;
      expect(figure.querySelector("[data-block-id=b]")).toBe(panel);
      expect(figure.querySelectorAll("img")).toHaveLength(failed ? 3 : 1);
      expect(figure.textContent).toBe(failed ? label.text : "");
    } finally {
      await act(() => root.unmount());
      container.remove();
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    }
    expect(revoke).toHaveBeenCalledWith("blob:figure");
    expect(signal?.aborted).toBe(true);
  });
});
