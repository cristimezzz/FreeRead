// 问答卡片：收起时只有 AI 标题；展开时是完整的一问一答（引用、选段下划线）、操作和输入框。
// 另外两种临时卡片：流式输出中的卡片、写新问题的草稿卡片（另起 / 新话题）。

import { type ComponentProps, type ReactNode, type RefObject } from "react";
import { Icon } from "../../components/icons";
import { PanelNote } from "../../components/SidePanel";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { cn } from "../../lib/utils";
import type { AnchorRange } from "./anchors";
import type { QaNode } from "./useQa";

// 流式原文里的引用标记（各种写法）：未校验，即时显示时先隐藏
const RAW_MARKER = /\s*[[【(（]\s*(?:d_[0-9a-f]+#)?b[_-]?\d+[^\]】)）]*[\]】)）]/gi;
// 校验后的答案只有 [b_0012] 一种写法
const MARKER = /\[(b_\d+)\]/g;
// 流式文本末尾还没写完的标记（如 "[b_00"）
const TRAILING_PARTIAL = /\s*[[【(（][^\]】)）]{0,24}$/;
// 流式文本末尾的卡片标题行（保存时由后端取出）
const TITLE_LINE = /\n\s*(?:\*\*)?(?:标题|Title)[\s\S]*$/i;

export const short = (s: string, n: number) => {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};
export const anchorOf = (n: QaNode) => (n.anchor?.text as string | undefined) ?? undefined;
export const titleOf = (n: QaNode) => n.title || short(n.question, 18);

export function streamingText(text: string) {
  return text.replace(TITLE_LINE, "").replace(RAW_MARKER, "").replace(TRAILING_PARTIAL, "");
}

export function CollapsedCard({
  title,
  full,
  anchored,
  active,
  onPath,
  onOpen,
}: {
  title: string;
  full: string;
  anchored?: boolean;
  active?: boolean;
  onPath?: boolean;
  onOpen: () => void;
}) {
  const cls = ["qa-card", anchored && "anchored", active && "active", onPath && "onpath"].filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} title={full} aria-current={active || undefined} onClick={onOpen}>
      {anchored && <span className="qa-card-mark">「」</span>}
      <span className="qa-card-title">{title}</span>
    </button>
  );
}

export interface ComposerProps {
  label: ReactNode;
  /** 标签旁的切换按钮（取消选段 / 改为新话题 …） */
  aside?: { text: string; onClick: () => void };
  draft: string;
  setDraft: (v: string) => void;
  running: boolean;
  onSend: () => void;
  onStop: () => void;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
  autoFocus?: boolean;
}

export function Composer({ label, aside, draft, setDraft, running, onSend, onStop, inputRef, autoFocus }: ComposerProps) {
  return (
    // 圆角输入卡：聚焦时整张卡片用强调色描边
    <div className="qa-card-composer bg-card focus-within:border-brand focus-within:ring-brand-soft rounded-2xl border border-input pt-3 pr-3 pb-2.5 pl-4 shadow-xs transition-[border-color,box-shadow] focus-within:ring-3">
      <div className="text-muted-foreground mb-1.5 flex items-center gap-2 text-xs">
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {aside && (
          <QaLink className="flex-none" onClick={aside.onClick}>
            {aside.text}
          </QaLink>
        )}
      </div>
      <Textarea
        className="max-h-40 min-h-11.5 resize-none rounded-none border-0 bg-transparent p-0 leading-normal shadow-none focus-visible:ring-0 dark:bg-transparent"
        ref={inputRef}
        value={draft}
        rows={2}
        autoFocus={autoFocus}
        placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"
        aria-label="问题"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSend();
          }
        }}
      />
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground flex-1 text-xs">只依据本文回答，并标出处</span>
        {running ? (
          <Button size="icon-sm" aria-label="停止" title="停止" onClick={onStop}>
            <span className="size-2.5 rounded-xs bg-current" />
          </Button>
        ) : (
          <Button size="icon-sm" aria-label="发送" title="发送" disabled={!draft.trim()} onClick={onSend}>
            <Icon name="send" strokeWidth={2} />
          </Button>
        )}
      </div>
    </div>
  );
}

export function Quote({ text }: { text: string }) {
  return <div className="qa-quote">「{short(text, 80)}」</div>;
}

export function ExpandedCard({
  node,
  anchors,
  cited,
  running,
  blockText,
  onPick,
  onAnchor,
  onRetake,
  onDiverge,
  onDelete,
  composer,
}: {
  node: QaNode;
  anchors: AnchorRange[];
  cited: string | null;
  running: boolean;
  blockText: (id: string) => string | undefined;
  onPick: (blockId: string) => void;
  onAnchor: (childId: string) => void;
  onRetake: () => void;
  onDiverge: () => void;
  onDelete: () => void;
  composer: ReactNode;
}) {
  const anchor = anchorOf(node);
  return (
    <article className={`qa-card expanded${anchor ? " anchored" : ""}`} aria-label={titleOf(node)}>
      <header className="qa-card-head">
        <span className="qa-card-title">{titleOf(node)}</span>
      </header>
      <div className="qa-card-body">
        {anchor && <Quote text={anchor} />}
        <div className="qa-question">{node.question}</div>
        <div className={`qa-answer${node.untraced ? " untraced" : ""}`} data-node={node.id}>
          {node.untraced && (
            <span className="nofound">
              <Icon name="alert" size={14} strokeWidth={1.8} />
              未找到依据
            </span>
          )}
          <div>{renderAnswer(node.answer, anchors, cited, blockText, onPick, onAnchor)}</div>
        </div>
        {node.status === "stale" && <PanelNote className="mx-0">原文已重新解析，部分引用已失效。</PanelNote>}
      </div>
      <div className="flex items-center gap-3.5">
        <QaLink disabled={running} onClick={onRetake}>
          重答
        </QaLink>
        <QaLink onClick={onDiverge}>
          另起
        </QaLink>
        <QaLink danger disabled={running} onClick={onDelete}>
          删除分支
        </QaLink>
        <span className="text-muted-foreground flex-1 text-right text-xs">选中回答里的文字可以就此追问</span>
      </div>
      {composer}
    </article>
  );
}

export function PendingCard({
  question,
  anchor,
  text,
  onStop,
}: {
  question: string;
  anchor?: string;
  text: string;
  onStop: () => void;
}) {
  const shown = streamingText(text);
  return (
    <article className="qa-card expanded pending" aria-busy="true">
      <header className="qa-card-head">
        <span className="qa-card-title">{short(question, 24)}</span>
        <QaLink onClick={onStop}>
          停止
        </QaLink>
      </header>
      <div className="qa-card-body">
        {anchor && <Quote text={anchor} />}
        <div className="qa-question">{question}</div>
        <div className="qa-answer">
          {shown ? (
            <span className="animate-in fade-in-0">{shown}</span>
          ) : (
            <span className="text-muted-foreground animate-in fade-in-0 text-[12.5px]">正在检索原文…</span>
          )}
        </div>
      </div>
    </article>
  );
}

export function DraftCard({ heading, composer }: { heading: string; composer: ReactNode }) {
  return (
    <article className="qa-card expanded draft">
      <header className="qa-card-head">
        <span className="qa-card-title">{heading}</span>
      </header>
      {composer}
    </article>
  );
}

/** [b_0012] → 编号标签（同一答案内按首次出现编号）；子卡片"就此追问"的选段加下划线，点它打开那张卡片。 */
function renderAnswer(
  text: string,
  anchors: AnchorRange[],
  cited: string | null,
  blockText: (id: string) => string | undefined,
  onPick: (id: string) => void,
  onAnchor: (childId: string) => void,
): ReactNode[] {
  const markers = new Map<number, { id: string; end: number }>();
  const cuts = new Set([0, text.length]);
  for (const m of text.matchAll(MARKER)) {
    const start = m.index ?? 0;
    markers.set(start, { id: m[1], end: start + m[0].length });
    cuts.add(start).add(start + m[0].length);
  }
  for (const a of anchors) cuts.add(a.start).add(a.end);
  const points = [...cuts].sort((x, y) => x - y);

  const numbers = new Map<string, number>();
  // 先切成片段，再把落在同一选段里的相邻片段包进一个 mark
  const groups: { anchor?: AnchorRange; parts: ReactNode[] }[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const marker = markers.get(a);
    let part: ReactNode;
    if (marker && marker.end === b) {
      if (!numbers.has(marker.id)) numbers.set(marker.id, numbers.size + 1);
      part = (
        <button
          type="button"
          key={`${a}-${marker.id}`}
          className={`cite${marker.id === cited ? " active" : ""}`}
          title={blockText(marker.id)?.slice(0, 200)}
          onClick={() => onPick(marker.id)}
        >
          {numbers.get(marker.id)}
        </button>
      );
    } else {
      part = text.slice(a, b);
    }
    const anchor = anchors.find((r) => a >= r.start && b <= r.end);
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.anchor === anchor) lastGroup.parts.push(part);
    else groups.push({ anchor, parts: [part] });
  }
  return groups.map((g, i) =>
    g.anchor ? (
      <mark
        key={`a-${g.anchor.id}`}
        className="qa-anchor"
        title="就此追问过：点击打开那张卡片"
        onClick={(e) => {
          if ((e.target as HTMLElement).closest(".cite")) return;
          onAnchor(g.anchor!.id);
        }}
      >
        {g.parts}
      </mark>
    ) : (
      <span key={`t-${i}`}>{g.parts}</span>
    ),
  );
}

/** 卡片里的文字按钮（重答、另起、停止 …）：灰色小字，悬停变深；danger 悬停变红。 */
function QaLink({ danger, className, ...rest }: ComponentProps<"button"> & { danger?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        "text-muted-foreground hover:text-foreground cursor-pointer text-xs transition-colors disabled:cursor-default disabled:opacity-40 disabled:hover:text-muted-foreground",
        danger && "hover:text-destructive",
        className,
      )}
      {...rest}
    />
  );
}
