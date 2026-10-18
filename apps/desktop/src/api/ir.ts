// Document IR 0.1 的前端类型（docs/02-document-ir.md、docs/schemas/ir-0.1.0.json）。只列阅读器用到的字段。

export type BlockType =
  | "title"
  | "author_info"
  | "abstract"
  | "heading"
  | "paragraph"
  | "list_item"
  | "equation"
  | "figure"
  | "table"
  | "caption"
  | "code"
  | "footnote"
  | "reference_entry"
  | "other";

export type BBox = [number, number, number, number];

export interface Anchor {
  page: number;
  bbox: BBox;
}

export interface Inline {
  key?: string;
  kind: "math" | "cite" | "xref" | "url" | "code";
  latex?: string;
  url?: string;
}

export interface Block {
  id: string;
  type: BlockType;
  order: number;
  section_id?: string;
  level?: number;
  text: string;
  inlines?: Inline[];
  latex?: string;
  html?: string;
  asset_id?: string;
  caption_of?: string;
  label?: string;
  anchors: Anchor[];
  flags?: string[];
}

export interface Asset {
  id: string;
  path: string;
  page?: number;
  width_px?: number;
  height_px?: number;
}

export interface PageInfo {
  index: number;
  width: number;
  height: number;
}

export interface Document {
  schema_version: string;
  doc_id: string;
  source: { pdf_sha256: string; page_count: number; pages: PageInfo[] };
  meta: { title?: string; language?: string };
  parser: { engine: string; engine_version: string };
  blocks: Block[];
  assets: Asset[];
}

export const PLACEHOLDER_RE = /⟦([A-Za-z0-9_]+)⟧/g;

export const TRANSLATABLE: ReadonlySet<BlockType> = new Set([
  "title",
  "abstract",
  "heading",
  "paragraph",
  "list_item",
  "caption",
  "footnote",
]);
