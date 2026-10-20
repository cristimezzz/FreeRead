// 重排视图：按 IR 渲染（docs/01-architecture.md §5.3）。每个节点带 data-block-id，
// 点击 → 原版定位；可视区域上报给翻译；译文按 对照 / 交替 / 仅译文 显示。

import { memo, useEffect, useMemo, useRef } from "react";
import type { Block, Document } from "../../api/ir";
import { TRANSLATABLE } from "../../api/ir";
import { pulse } from "../../components/motion";
import type { TranslationState } from "../translate/useTranslations";
import { useAssetUrl } from "./useAssetUrl";
import { renderMath, renderTableHtml, splitPlaceholders } from "./render";

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

  return (
    <div className="reader-pane">
      <article
        ref={root}
        className="reflow"
        data-mode={p.mode}
        lang={p.doc.meta.language ?? undefined}
        style={{ "--reflow-font-size": `${p.fontSize}px` } as React.CSSProperties}
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
}

const BlockView = memo(function BlockView({ block, docId, assetPath, assetVersion, mode, translation, located, onLocate }: BlockProps) {
  const original = (
    <BlockBody block={block} text={block.text} docId={docId} assetPath={assetPath} assetVersion={assetVersion} />
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
      <div className="rf-pending">翻译中…</div>
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
      onClick={() => onLocate(block)}
    >
      {content}
    </div>
  );
});

function Inline({ text, block }: { text: string; block: Block }) {
  const segments = useMemo(() => splitPlaceholders(text, block.inlines), [text, block.inlines]);
  return (
    <>
      {segments.map((s, i) =>
        s.kind === "text" ? (
          <span key={i}>{s.text}</span>
        ) : s.kind === "math" ? (
          <span key={i} dangerouslySetInnerHTML={{ __html: renderMath(s.latex) }} />
        ) : (
          <span key={i}>{`⟦${s.key}⟧`}</span>
        ),
      )}
    </>
  );
}

function BlockBody({
  block,
  text,
  docId,
  assetPath,
  assetVersion,
}: {
  block: Block;
  text: string;
  docId: string;
  assetPath?: string;
  assetVersion?: string;
}) {
  const inline = <Inline text={text} block={block} />;
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
