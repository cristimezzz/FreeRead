import type { Anchor, BBox, Block } from "../../api/ir";

const FIGURE_CAPTION = /^\s*(?:(?:supplementary\s+|extended\s+data\s+)?fig(?:ure)?s?\.?|scheme|图)\s*S?\d/i;
const PANEL_LABEL = /^\s*[(\[]?(?:[a-z]|[ivx]{1,4})[)\]]?[.:]?\s*$/i;
const PANEL_GAP = 40;
const LABEL_GAP = 10;

interface PlacedBlock {
  block: Block;
  bbox: BBox;
}

export interface FigureGroup extends Anchor {
  caption: Block;
  captionAbove: boolean;
  panels: PlacedBlock[];
  labels: PlacedBlock[];
}

const width = (b: BBox) => b[2] - b[0];
const height = (b: BBox) => b[3] - b[1];
const overlapX = (a: BBox, b: BBox) => Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
const overlapY = (a: BBox, b: BBox) => Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
const overlaps = (a: BBox, b: BBox) => overlapX(a, b) > 0 && overlapY(a, b) > 0;
const union = (a: BBox, b: BBox): BBox => [
  Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3]),
];

function adjacent(a: BBox, b: BBox, gap: number): boolean {
  const x = overlapX(a, b);
  const y = overlapY(a, b);
  return (x >= -gap && y >= 0.25 * Math.min(height(a), height(b))) ||
    (y >= -gap && x >= 0.25 * Math.min(width(a), width(b)));
}

function isPanelLabel(block: Block): boolean {
  return (block.type === "caption" || block.type === "paragraph" || block.type === "other" ||
    block.type === "heading") && PANEL_LABEL.test(block.text);
}

export function groupFigures(blocks: Block[]): FigureGroup[] {
  const pages = new Map<number, PlacedBlock[]>();
  for (const block of blocks) {
    for (const { page, bbox } of block.anchors) {
      if (!Number.isInteger(page) || page < 0 || !bbox.every(Number.isFinite) ||
          width(bbox) <= 0 || height(bbox) <= 0) continue;
      let placed = pages.get(page);
      if (!placed) pages.set(page, placed = []);
      placed.push({ block, bbox });
    }
  }

  const groups: FigureGroup[] = [];
  const claims = new Map<string, number>();
  for (const [page, placed] of pages) {
    const figures = placed.filter(({ block }) =>
      block.type === "figure" && block.asset_id && block.anchors.length === 1);
    if (figures.length < 2) continue;
    const captions = placed.filter(({ block }) => block.type === "caption" &&
      (FIGURE_CAPTION.test(block.text) || FIGURE_CAPTION.test(block.label ?? "")));
    for (const { block: caption, bbox: captionBox } of captions) {
      if (caption.anchors.length !== 1) continue;
      const seed = figures.find(({ block }) => block.id === caption.caption_of);
      if (!seed) continue;
      const captionAbove = captionBox[3] <= seed.bbox[1];
      const onFigureSide = (bbox: BBox) =>
        captionAbove ? bbox[1] >= captionBox[3] : bbox[3] <= captionBox[1];
      const fitsCaption = (bbox: BBox) => onFigureSide(bbox) &&
        overlapX(bbox, captionBox) >= 0.5 * Math.min(width(bbox), width(captionBox));
      const gapToCaption = captionAbove ? seed.bbox[1] - captionBox[3] : captionBox[1] - seed.bbox[3];
      if (!fitsCaption(seed.bbox) || gapToCaption > PANEL_GAP) continue;

      const otherTargets = new Set(captions.filter(({ block }) => block.id !== caption.id)
        .map(({ block }) => block.caption_of));
      if (otherTargets.has(seed.block.id)) continue;
      const candidates = figures.filter(({ block, bbox }) =>
        block.id !== seed.block.id && !otherTargets.has(block.id) && fitsCaption(bbox));
      const panels = [seed];
      const members = new Set([seed.block.id]);
      for (const panel of panels) {
        for (const candidate of candidates) {
          if (members.has(candidate.block.id) || !adjacent(panel.bbox, candidate.bbox, PANEL_GAP)) continue;
          members.add(candidate.block.id);
          panels.push(candidate);
        }
      }
      if (panels.length < 2) continue;

      const labels = placed.filter(({ block, bbox }) => block.anchors.length === 1 &&
        isPanelLabel(block) && onFigureSide(bbox) && panels.some((p) => adjacent(p.bbox, bbox, LABEL_GAP)));
      const bbox = [...panels, ...labels].map((p) => p.bbox).reduce(union);
      for (const label of labels) members.add(label.block.id);
      if (placed.some((p) => !members.has(p.block.id) && overlaps(bbox, p.bbox))) continue;

      const byOrder = (a: PlacedBlock, b: PlacedBlock) => a.block.order - b.block.order;
      groups.push({ caption, captionAbove, page, bbox, panels: panels.sort(byOrder), labels: labels.sort(byOrder) });
      for (const id of members) claims.set(id, (claims.get(id) ?? 0) + 1);
    }
  }
  return groups.filter(({ panels, labels }) => [...panels, ...labels].every(({ block }) => claims.get(block.id) === 1));
}
