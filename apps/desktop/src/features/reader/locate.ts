// 原版 ⇄ 重排双向定位（docs/01-architecture.md §5.3）。坐标为 PDF 点（pt），左上原点。

import type { Anchor, BBox, Block } from "../../api/ir";

interface Entry {
  id: string;
  bbox: BBox;
  area: number;
}

export type PageIndex = Map<number, Entry[]>;

/** 每页的 bbox 索引。跨页段落有多个 anchor，每个都登记。 */
export function buildPageIndex(blocks: Block[]): PageIndex {
  const index: PageIndex = new Map();
  for (const b of blocks) {
    for (const a of b.anchors) {
      const [x0, y0, x1, y1] = a.bbox;
      const list = index.get(a.page) ?? [];
      list.push({ id: b.id, bbox: a.bbox, area: Math.max(0, x1 - x0) * Math.max(0, y1 - y0) });
      index.set(a.page, list);
    }
  }
  return index;
}

const contains = ([x0, y0, x1, y1]: BBox, x: number, y: number, pad = 0) =>
  x >= x0 - pad && x <= x1 + pad && y >= y0 - pad && y <= y1 + pad;

const distance = ([x0, y0, x1, y1]: BBox, x: number, y: number) => {
  const dx = Math.max(x0 - x, 0, x - x1);
  const dy = Math.max(y0 - y, 0, y - y1);
  return Math.hypot(dx, dy);
};

/**
 * 点击位置 → 块：优先选包含该点的最小块（图注压在图上时选图注）；
 * 都不包含时取 tolerance 以内最近的块（点在行间空白处）。
 */
export function blockAt(index: PageIndex, page: number, x: number, y: number, tolerance = 8): string | null {
  const entries = index.get(page);
  if (!entries?.length) return null;
  const hits = entries.filter((e) => contains(e.bbox, x, y));
  if (hits.length) return hits.reduce((a, b) => (b.area < a.area ? b : a)).id;
  let best: Entry | null = null;
  let bestD = tolerance;
  for (const e of entries) {
    const d = distance(e.bbox, x, y);
    if (d <= bestD) {
      best = e;
      bestD = d;
    }
  }
  return best?.id ?? null;
}

/** 阅读位置：块的第一个 anchor。 */
export function primaryAnchor(block: Block | undefined): Anchor | null {
  return block?.anchors[0] ?? null;
}
