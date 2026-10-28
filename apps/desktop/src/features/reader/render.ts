// 块内容渲染：⟦EQn⟧ 占位符 → KaTeX；表格 HTML 先净化再渲染其中的 <math>LaTeX</math>。
// LLM 输出与引擎输出都不可信，一律经过 DOMPurify / KaTeX 转义（architecture §10）。

import DOMPurify from "dompurify";
import katex from "katex";
import type { Inline } from "../../api/ir";
import { PLACEHOLDER_RE } from "../../api/ir";

export type Segment = { kind: "text"; text: string } | { kind: "math"; latex: string } | { kind: "raw"; key: string };

/** 把含占位符的文本切成片段。找不到 latex 的占位符原样保留（raw）。 */
export function splitPlaceholders(text: string, inlines: Inline[] = []): Segment[] {
  const byKey = new Map(inlines.filter((i) => i.key).map((i) => [i.key as string, i]));
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push({ kind: "text", text: text.slice(last, idx) });
    const inline = byKey.get(m[1]);
    if (inline?.kind === "math" && inline.latex) out.push({ kind: "math", latex: inline.latex });
    else out.push({ kind: "raw", key: m[1] });
    last = idx + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

// katex.renderToString 是同步的，一篇论文有几百条公式；打开文档、翻译进度更新、批注变化都会重新渲染块，按公式缓存结果
const MATH_CACHE_MAX = 2000;
const mathCache = new Map<string, string>();

export function renderMath(latex: string, displayMode = false): string {
  const key = `${displayMode ? "d" : "i"}:${latex}`;
  const hit = mathCache.get(key);
  if (hit !== undefined) return hit;
  const html = katex.renderToString(latex, { displayMode, throwOnError: false, strict: "ignore", trust: false });
  if (mathCache.size >= MATH_CACHE_MAX) mathCache.delete(mathCache.keys().next().value!);
  mathCache.set(key, html);
  return html;
}

const TABLE_TAGS = ["table", "thead", "tbody", "tfoot", "tr", "td", "th", "math", "sup", "sub", "b", "i", "br"];

function unescapeHtml(s: string): string {
  const el = document.createElement("textarea");
  el.innerHTML = s;
  return el.value;
}

export function renderTableHtml(html: string): string {
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: TABLE_TAGS,
    ALLOWED_ATTR: ["rowspan", "colspan"],
  });
  return clean.replace(/<math>([\s\S]*?)<\/math>/g, (_, tex: string) => renderMath(unescapeHtml(tex)));
}
