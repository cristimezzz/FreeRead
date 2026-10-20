// 批注区间与渲染：区间是块 text（含 ⟦KEY⟧ 占位符）里的字符偏移，和 Core 存的一致。
// 重排视图里每个叶子节点带 data-off（起始偏移）和 data-len（占的字符数，公式按整个占位符算），
// 选区据此换算回偏移；公式只能整个选中或不选。

import type { Inline } from "../../api/ir";
import { splitPlaceholders, type Segment } from "../reader/render";

export type PlacedSegment = Segment & { start: number; end: number };

export interface Mark {
  id: string;
  start: number;
  end: number;
  color: string;
  hasNote: boolean;
}

export type Piece = { text: string; start: number; mark?: Mark };

/** splitPlaceholders 的结果加上在原文里的偏移。 */
export function placeSegments(text: string, inlines: Inline[] = []): PlacedSegment[] {
  let pos = 0;
  return splitPlaceholders(text, inlines).map((s) => {
    // math / raw 段在原文里是整个占位符：从 pos 开始找下一个 ⟦…⟧
    const len = s.kind === "text" ? s.text.length : text.indexOf("⟧", pos) + 1 - pos;
    const placed = { ...s, start: pos, end: pos + len };
    pos += len;
    return placed;
  });
}

/** 把一个文本段按批注切开；重叠时后面的批注优先（不嵌套 <mark>）。 */
export function splitByMarks(text: string, start: number, marks: Mark[]): Piece[] {
  const end = start + text.length;
  const cuts = new Set([start, end]);
  for (const m of marks) {
    if (m.end <= start || m.start >= end) continue;
    cuts.add(Math.max(start, m.start));
    cuts.add(Math.min(end, m.end));
  }
  const points = [...cuts].sort((a, b) => a - b);
  const pieces: Piece[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [a, b] = [points[i], points[i + 1]];
    const mark = [...marks].reverse().find((m) => m.start <= a && m.end >= b);
    const prev = pieces[pieces.length - 1];
    if (prev && prev.mark === mark) prev.text += text.slice(a - start, b - start);
    else pieces.push({ text: text.slice(a - start, b - start), start: a, mark });
  }
  return pieces;
}

function leafOf(node: Node): HTMLElement | null {
  const el = node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : node.parentElement;
  return el?.closest<HTMLElement>("[data-off]") ?? null;
}

/** 选区一端 → 块内偏移。edge=start 时公式取起点，end 时取终点。 */
function offsetAt(container: Node, offset: number, edge: "start" | "end"): number | null {
  const leaf = leafOf(container);
  if (!leaf) return null;
  const base = Number(leaf.dataset.off);
  const len = Number(leaf.dataset.len);
  if (leaf.dataset.kind !== "text") return edge === "start" ? base : base + len;
  if (container.nodeType === Node.TEXT_NODE) return base + Math.min(offset, len);
  // 选区落在元素边界上：offset 是子节点下标
  return offset === 0 ? base : base + len;
}

/**
 * 当前选区 → { blockId, start, end }。只接受落在同一个块的原文里（不含译文）、非空的选区。
 * root 是重排视图的容器。
 */
export function selectionRange(root: HTMLElement, range: Range): { blockId: string; start: number; end: number } | null {
  if (range.collapsed) return null;
  const startEl = leafOf(range.startContainer);
  const endEl = leafOf(range.endContainer);
  if (!startEl || !endEl || !root.contains(startEl)) return null;
  const block = startEl.closest<HTMLElement>("[data-block-id]");
  if (!block || block !== endEl.closest("[data-block-id]")) return null;
  if (startEl.closest(".rf-translation") || endEl.closest(".rf-translation")) return null;
  const start = offsetAt(range.startContainer, range.startOffset, "start");
  const end = offsetAt(range.endContainer, range.endOffset, "end");
  if (start === null || end === null || end <= start) return null;
  return { blockId: block.dataset.blockId!, start, end };
}
