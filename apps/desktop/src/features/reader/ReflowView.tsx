// 重排视图：按 IR 渲染（docs/01-architecture.md §5.3）。每个节点带 data-block-id，
// 点击 → 原版定位；可视区域上报给翻译；译文按 对照 / 交替 / 仅译文 显示。
// 原文选中文字后浮出高亮工具条；已有高亮画成 <mark>（features/annotations）。

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Block, Document } from "../../api/ir";
import { TRANSLATABLE } from "../../api/ir";
import { pulse } from "../../components/motion";
import { type Mark, placeSegments, selectionRange, splitByMarks } from "../annotations/offsets";
import { COLORS, type AnnotationColor } from "../annotations/useAnnotations";
import { Shimmer } from "../../components/ai-elements/shimmer";
import type { TranslationState } from "../translate/useTranslations";
import { useAssetUrl } from "./useAssetUrl";
import { renderMath, renderTableHtml } from "./render";

export type TranslationMode = "off" | "side" | "alternate" | "only";

interface Props {
  doc: Document;
  mode: TranslationMode;
  translations: Record<string, TranslationState>;
  located: string | null;
  /** 每次变化时滚动到 located（定位来自原版视图时） */
  scrollKey: number;
  fontSize: number;
  onLocate: (block: Block) => void;
  onVisible: (ids: string[]) => void;
  /** 块 ID → 区间高亮 */
  marks?: Record<string, Mark[]>;
  /** 块 ID → 整块高亮的颜色 */
  wholeMarks?: Record<string, string>;
  /** 选中原文后点颜色（note=true 表示"加批注"） */
  onAnnotate?: (sel: { blockId: string; start: number; end: number }, color: AnnotationColor, note: boolean) => void;
  onMarkClick?: (annotationId: string) => void;
}

const NO_MARKS: Mark[] = [];

interface Toolbar {
  sel: { blockId: string; start: number; end: number };
  x: number;
  y: number;
}

export function ReflowView(p: Props) {
  const root = useRef<HTMLDivElement>(null);
  const visible = useRef(new Set<string>());
  const order = useMemo(() => new Map(p.doc.blocks.map((b, i) => [b.id, i])), [p.doc]);
  const onVisible = useRef(p.onVisible);
  onVisible.current = p.onVisible;

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    visible.current.clear(); // IR 重新加载后旧节点已卸载，不会再收到"离开视口"的通知
    const report = () =>
      onVisible.current([...visible.current].sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0)));
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const id = (e.target as HTMLElement).dataset.blockId;
          if (!id) continue;
          if (e.isIntersecting) visible.current.add(id);
          else visible.current.delete(id);
        }
        report();
      },
      // 预取：视口上下各一屏
      { root: el.parentElement, rootMargin: "100% 0px" },
    );
    el.querySelectorAll("[data-block-id]").forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, [p.doc, order]);

  useEffect(() => {
    if (!p.located) return;
    const el = root.current?.querySelector(`[data-block-id="${p.located}"]`);
    if (!el) return;
    // 远距离跳转（如搜索结果）直接定位：平滑滚动途中图片加载会改变布局，常常停在半路
    const far = Math.abs(el.getBoundingClientRect().top) > 2 * window.innerHeight;
    el.scrollIntoView({ behavior: far ? "auto" : "smooth", block: "center" });
    pulse(el);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.scrollKey]);

  const assets = useMemo(() => new Map(p.doc.assets.map((a) => [a.id, a])), [p.doc]);

  // 选中原文 → 浮出高亮工具条（fixed 定位在选区上方）
  const [toolbar, setToolbar] = useState<Toolbar | null>(null);
  const canAnnotate = Boolean(p.onAnnotate);
  const onMouseUp = useCallback(() => {
    if (!canAnnotate) return;
    // 等浏览器更新完选区
    setTimeout(() => {
      const s = window.getSelection();
      const range = s && s.rangeCount ? s.getRangeAt(0) : null;
      const sel = range && root.current ? selectionRange(root.current, range) : null;
      if (!sel || !range) return setToolbar(null);
      const rect = range.getBoundingClientRect();
      setToolbar({ sel, x: rect.left + rect.width / 2, y: rect.top });
    }, 0);
  }, [canAnnotate]);
  useEffect(() => {
    if (!toolbar) return;
    const hide = () => setToolbar(null);
    const pane = root.current?.parentElement;
    pane?.addEventListener("scroll", hide, { passive: true });
    window.addEventListener("resize", hide);
    return () => {
      pane?.removeEventListener("scroll", hide);
      window.removeEventListener("resize", hide);
    };
  }, [toolbar]);
  const annotate = (color: AnnotationColor, note: boolean) => {
    if (!toolbar) return;
    p.onAnnotate?.(toolbar.sel, color, note);
    window.getSelection()?.removeAllRanges();
    setToolbar(null);
  };

  return (
    <div className="reader-pane">
      {toolbar && (
        <div
          className="sel-toolbar"
          role="toolbar"
          aria-label="高亮"
          style={{ left: toolbar.x, top: toolbar.y }}
          onMouseDown={(e) => e.preventDefault()} // 不要清掉选区
        >
          {COLORS.map((c) => (
            <button
              key={c.value}
              type="button"
              className="sel-color"
              data-color={c.value}
              aria-label={`${c.label}色高亮`}
              title={`${c.label}色高亮`}
              onClick={() => annotate(c.value, false)}
            />
          ))}
          <button type="button" className="sel-note" onClick={() => annotate("yellow", true)}>
            批注
          </button>
        </div>
      )}
      <article
        ref={root}
        className="reflow"
        data-mode={p.mode}
        lang={p.doc.meta.language ?? undefined}
        style={{ "--reflow-font-size": `${p.fontSize}px` } as React.CSSProperties}
        onMouseUp={onMouseUp}
        onMouseDown={() => toolbar && setToolbar(null)}
      >
        {p.doc.blocks.map((b) => (
          <BlockView
            key={b.id}
            block={b}
            docId={p.doc.doc_id}
            assetPath={b.asset_id ? assets.get(b.asset_id)?.path : undefined}
            assetVersion={p.doc.parser.created_at}
            mode={TRANSLATABLE.has(b.type) ? p.mode : "off"}
            translation={p.translations[b.id]}
            located={p.located === b.id}
            onLocate={p.onLocate}
            marks={p.marks?.[b.id] ?? NO_MARKS}
            wholeMark={p.wholeMarks?.[b.id]}
            onMarkClick={p.onMarkClick}
          />
        ))}
      </article>
    </div>
  );
}

interface BlockProps {
  block: Block;
  docId: string;
  assetPath?: string;
  assetVersion?: string;
  mode: TranslationMode;
  translation?: TranslationState;
  located: boolean;
  onLocate: (b: Block) => void;
  marks: Mark[];
  wholeMark?: string;
  onMarkClick?: (annotationId: string) => void;
}

const BlockView = memo(function BlockView({
  block,
  docId,
  assetPath,
  assetVersion,
  mode,
  translation,
  located,
  onLocate,
  marks,
  wholeMark,
  onMarkClick,
}: BlockProps) {
  const original = (
    <BlockBody
      block={block}
      text={block.text}
      docId={docId}
      assetPath={assetPath}
      assetVersion={assetVersion}
      source={{ marks, onMarkClick }}
    />
  );
  let content = original;
  if (mode !== "off") {
    const done = translation && (translation.status === "ok" || translation.status === "needs_review");
    const translated = done ? (
      <div className="rf-translation" lang="zh">
        <BlockBody block={block} text={translation.text} docId={docId} />
        {translation.status === "needs_review" && <div className="rf-review">译文未通过校验，显示原文</div>}
      </div>
    ) : translation?.status === "pending" ? (
      <div className="rf-pending">
        <Shimmer>翻译中…</Shimmer>
      </div>
    ) : translation?.status === "error" ? (
      <div className="rf-review">翻译失败：{translation.message}</div>
    ) : null;
    if (mode === "only") content = done ? translated! : <>{original}{translated}</>;
    else
      content = (
        <div className="rf-pair" data-mode={mode}>
          {original}
          {translated ?? (mode === "side" ? <div /> : null)}
        </div>
      );
  }
  return (
    <div
      className={`rf-block${located ? " located" : ""}`}
      data-block-id={block.id}
      data-type={block.type}
      data-mark={wholeMark}
      onClick={() => onLocate(block)}
    >
      {content}
    </div>
  );
});

/** 原文才有：叶子节点带偏移（选区换算），文本按高亮切开 */
interface Source {
  marks: Mark[];
  onMarkClick?: (annotationId: string) => void;
}

function Inline({ text, block, source }: { text: string; block: Block; source?: Source }) {
  const segments = useMemo(() => placeSegments(text, block.inlines), [text, block.inlines]);
  return (
    <>
      {segments.map((s, i) => {
        const off = source ? { "data-off": s.start, "data-len": s.end - s.start, "data-kind": s.kind } : {};
        if (s.kind === "math") return <span key={i} {...off} dangerouslySetInnerHTML={{ __html: renderMath(s.latex) }} />;
        if (s.kind === "raw") return <span key={i} {...off}>{`⟦${s.key}⟧`}</span>;
        if (!source?.marks.length) return <span key={i} {...off}>{s.text}</span>;
        return splitByMarks(s.text, s.start, source.marks).map((piece, j) => {
          const attrs = { "data-off": piece.start, "data-len": piece.text.length, "data-kind": "text" };
          const m = piece.mark;
          return m ? (
            <mark
              key={`${i}.${j}`}
              {...attrs}
              className="rf-mark"
              data-color={m.color}
              data-note={m.hasNote ? "" : undefined}
              onClick={(e) => {
                // 有选区时是在选文字，不是点高亮
                if (window.getSelection()?.isCollapsed === false) return;
                e.stopPropagation();
                source.onMarkClick?.(m.id);
              }}
            >
              {piece.text}
            </mark>
          ) : (
            <span key={`${i}.${j}`} {...attrs}>
              {piece.text}
            </span>
          );
        });
      })}
    </>
  );
}

function BlockBody({
  block,
  text,
  docId,
  assetPath,
  assetVersion,
  source,
}: {
  block: Block;
  text: string;
  docId: string;
  assetPath?: string;
  assetVersion?: string;
  source?: Source;
}) {
  const inline = <Inline text={text} block={block} source={source} />;
  switch (block.type) {
    case "title":
      return <h1 className="rf-title">{inline}</h1>;
    case "author_info":
      return <p className="rf-authors">{inline}</p>;
    case "abstract":
      return <div className="rf-abstract">{inline}</div>;
    case "heading": {
      const level = Math.min(4, Math.max(2, (block.level ?? 1) + 1));
      const Tag = `h${level}` as "h2" | "h3" | "h4";
      return <Tag>{inline}</Tag>;
    }
    case "list_item":
      return <p style={{ paddingLeft: "1.2em", textIndent: "-0.8em" }}>• {inline}</p>;
    case "equation":
      return block.latex ? (
        <div className="rf-equation" dangerouslySetInnerHTML={{ __html: renderMath(block.latex, true) }} />
      ) : (
        <div className="rf-equation">{inline}</div>
      );
    case "figure":
      return (
        <figure>
          <AssetImage docId={docId} path={assetPath} version={assetVersion} alt={block.label ?? "图"} />
        </figure>
      );
    case "table":
      return block.html ? (
        <div className="rf-table" dangerouslySetInnerHTML={{ __html: renderTableHtml(block.html) }} />
      ) : (
        <figure>
          <AssetImage docId={docId} path={assetPath} version={assetVersion} alt={block.label ?? "表"} />
        </figure>
      );
    case "caption":
      return <p className="rf-caption">{inline}</p>;
    case "code":
      return <pre>{text}</pre>;
    case "footnote":
      return <p className="rf-footnote">{inline}</p>;
    case "reference_entry":
      return <p className="rf-reference">{inline}</p>;
    default:
      return <p>{inline}</p>;
  }
}

function AssetImage({ docId, path, version, alt }: { docId: string; path?: string; version?: string; alt: string }) {
  const url = useAssetUrl(docId, path, version);
  if (!url) return <div className="rf-pending">（图片加载中）</div>;
  return <img src={url} alt={alt} loading="lazy" />;
}
