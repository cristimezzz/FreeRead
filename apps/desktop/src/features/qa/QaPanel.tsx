import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "../../components/icons";
import { Button, Dialog, IconButton, Select } from "../../components/ui";
import { anchorRanges, type AnchorRange } from "./anchors";
import { QaCanvas, type CanvasItem } from "./QaCanvas";
import { buildTree, pathTo, siblings } from "./tree";
import type { QaNode, useQa } from "./useQa";

interface Props {
  state: ReturnType<typeof useQa>;
  /** 引用块的原文（悬停提示用） */
  blockText: (id: string) => string | undefined;
  onPick: (blockId: string) => void;
  onClose: () => void;
  /** 展开后问答树铺满阅读区：覆盖层元素由 ReaderView 提供 */
  expanded: boolean;
  stage: HTMLElement | null;
  onExpand: (expanded: boolean) => void;
}

const NEW = "__new__";
const PENDING = "__pending__";
// 流式原文里的引用标记（各种写法）：未校验，即时显示时先隐藏
const RAW_MARKER = /\s*[[【(（]\s*(?:d_[0-9a-f]+#)?b[_-]?\d+[^\]】)）]*[\]】)）]/gi;
// 校验后的答案只有 [b_0012] 一种写法
const MARKER = /\[(b_\d+)\]/g;
// 流式文本末尾还没写完的标记（如 "[b_00"）
const TRAILING_PARTIAL = /\s*[[【(（][^\]】)）]{0,24}$/;

const short = (s: string, n: number) => {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};
const anchorOf = (n: QaNode) => (n.anchor?.text as string | undefined) ?? undefined;

export function QaPanel({ state, blockText, onPick, onClose, expanded, stage, onExpand }: Props) {
  const { sessions, current, nodes, tree, active, target, pending, running, error, lastModes } = state;
  const { select, ask, cancel, remove, focus, switchTo, diverge, retake, spawnFromSelection, newTopic, removeNode } =
    state;
  const [draft, setDraft] = useState("");
  const [cited, setCited] = useState<string | null>(null);
  const [showTree, setShowTree] = useState(true);
  const [doomed, setDoomed] = useState<QaNode | null>(null);
  const [selPop, setSelPop] = useState<{ id: string; text: string; x: number; y: number } | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  // 刚流式写完的那一轮由 pending 换成正式节点：不再播放一次入场动画
  const hadPending = useRef(false);
  const settled = useRef<string | null>(null);
  if (hadPending.current && !pending && nodes.length) settled.current = nodes[nodes.length - 1].id;
  hadPending.current = Boolean(pending);

  // 阅读区：根到当前节点的路径；提问中显示到新问题的父节点为止，再接上流式的这一轮
  const path = useMemo(() => pathTo(tree, pending ? pending.parentId : active), [tree, pending, active]);
  const onPath = useMemo(() => new Set([...path.map((n) => n.id), ...(pending ? [PENDING] : [])]), [path, pending]);

  // 画布：正式节点加上流式中的占位节点
  const canvasTree = useMemo(() => {
    const items: CanvasItem[] = nodes.map((n) => ({
      id: n.id,
      parent_id: n.parent_id,
      question: n.question,
      anchored: Boolean(anchorOf(n)),
    }));
    if (pending) items.push({ id: PENDING, parent_id: pending.parentId, question: pending.question, pending: true });
    return buildTree(items);
  }, [nodes, pending]);

  // 新内容出现、切换分支时滚到底部
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight });
  }, [path, pending?.text]);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onExpand(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded, onExpand]);

  const send = () => {
    if (!draft.trim() || running) return;
    void ask(draft);
    setDraft("");
  };

  const pick = (id: string) => {
    setCited(id);
    onPick(id);
  };

  const followUp = (id: string) => {
    focus(id);
    input.current?.focus();
  };

  // 在回答里选中文字：浮出"就此追问"
  const onSelect = () => {
    const sel = window.getSelection();
    const box = list.current;
    if (!sel || sel.isCollapsed || !sel.rangeCount || !box) return setSelPop(null);
    const range = sel.getRangeAt(0);
    const answerOf = (n: Node | null) =>
      (n instanceof Element ? n : n?.parentElement)?.closest<HTMLElement>(".qa-answer[data-node]");
    const a = answerOf(range.startContainer);
    if (!a || a !== answerOf(range.endContainer)) return setSelPop(null);
    const frag = range.cloneContents();
    frag.querySelectorAll(".cite, .nofound").forEach((el) => el.remove());
    const text = (frag.textContent ?? "").replace(/\s+/g, " ").trim();
    if (text.length < 2) return setSelPop(null);
    const r = range.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    setSelPop({
      id: a.dataset.node!,
      text: text.slice(0, 500),
      x: Math.min(Math.max(r.left + r.width / 2 - b.left, 48), b.width - 48),
      y: r.top - b.top + box.scrollTop,
    });
  };

  const spawn = () => {
    if (!selPop) return;
    spawnFromSelection(selPop.id, selPop.text);
    setDraft(`「${short(selPop.text, 40)}」是什么意思？`);
    setSelPop(null);
    window.getSelection()?.removeAllRanges();
    input.current?.focus();
  };

  const noVector = lastModes && !lastModes.includes("vector");
  const parentNode = target.parentId ? tree.byId.get(target.parentId) : undefined;
  const beside = target.besideId ? tree.byId.get(target.besideId) : undefined;

  const canvas = (cls?: string) => (
    <QaCanvas tree={canvasTree} active={pending ? PENDING : active} onPath={onPath} onPick={switchTo} className={cls} />
  );

  return (
    <aside className="side-panel qa-panel" aria-label="问答">
      <div className="side-panel-head qa-head">
        <h2 className="serif">问答</h2>
        <Select
          label="对话"
          hideLabel
          className="convsel"
          value={current ?? NEW}
          options={[
            ...(current ? [] : [{ value: NEW, label: "新对话" }]),
            ...sessions.map((s) => ({ value: s.id, label: s.title || "未命名对话" })),
          ]}
          onValue={(v) => void select(v === NEW ? null : v)}
        />
        {nodes.length > 0 && (
          <>
            <IconButton
              icon="graph"
              label={showTree ? "隐藏问答树" : "显示问答树"}
              active={showTree && !expanded}
              disabled={expanded}
              onClick={() => setShowTree((v) => !v)}
            />
            <IconButton
              icon={expanded ? "collapse" : "expand"}
              label={expanded ? "收起问答树（Esc）" : "展开问答树到阅读区"}
              onClick={() => onExpand(!expanded)}
            />
          </>
        )}
        <IconButton icon="add" label="新对话" disabled={!current} onClick={() => void select(null)} />
        <IconButton
          icon="delete"
          label="删除对话"
          disabled={!current || running}
          onClick={() => current && void remove(current)}
        />
        <IconButton icon="close" label="关闭问答" onClick={onClose} />
      </div>

      {nodes.length > 0 &&
        (expanded && stage
          ? createPortal(
              <div className="kg-stage-inner qa-stage-inner">
                {canvas("fill")}
                <Button small icon="collapse" className="kg-stage-close" onClick={() => onExpand(false)}>
                  收起（Esc）
                </Button>
              </div>,
              stage,
            )
          : showTree && canvas())}

      <div
        className="qa-messages"
        ref={list}
        onMouseUp={onSelect}
        onKeyUp={(e) => e.shiftKey && onSelect()}
        onScroll={() => selPop && setSelPop(null)}
      >
        {!nodes.length && !pending && (
          <p className="search-note">
            就这篇论文提问，回答会标出依据的原文，点编号可以跳回原文。每个回答都可以追问、重答或另起一支，选中回答里的文字可以就此追问，对话会长成一棵问答树。提问会把检索到的段落发送给问答所用的大模型服务（默认与总结相同）。
          </p>
        )}
        {path.map((n) => (
          <Turn
            key={n.id}
            node={n}
            enter={n.id !== settled.current}
            siblings={siblings(tree, n.id)}
            anchors={anchorRanges(
              n.answer,
              (tree.children.get(n.id) ?? []).flatMap((c) => (anchorOf(c) ? [{ id: c.id, text: anchorOf(c)! }] : [])),
            )}
            cited={cited}
            running={running}
            blockText={blockText}
            onPick={pick}
            onSwitch={switchTo}
            onFollowUp={followUp}
            onRetake={retake}
            onDiverge={(id) => {
              diverge(id);
              input.current?.focus();
            }}
            onDelete={setDoomed}
          />
        ))}
        {pending && (
          <div className="qa-turn enter">
            {pending.anchor && <Quote text={pending.anchor} />}
            <div className="qa-question">{pending.question}</div>
            <div className="qa-answer">
              {pending.text ? (
                <span className="fade-in">{pending.text.replace(RAW_MARKER, "").replace(TRAILING_PARTIAL, "")}</span>
              ) : (
                <span className="search-note fade-in">正在检索原文…</span>
              )}
            </div>
          </div>
        )}
        {error && <p className="search-note error">{error}</p>}
        {selPop && (
          <button
            type="button"
            className="qa-sel-pop"
            style={{ left: selPop.x, top: selPop.y }}
            onMouseDown={(e) => e.preventDefault()}
            onClick={spawn}
          >
            就此追问
          </button>
        )}
      </div>

      {noVector && (
        <p className="search-note">
          这篇论文还没有语义索引，只按关键词找原文，回答可能不全。可在 设置 › 检索 中下载嵌入模型。
        </p>
      )}
      <div className="composer">
        {nodes.length > 0 && (
          <div className="composer-target">
            {target.anchor ? (
              <span>
                就此追问 ·「{short(target.anchor, 28)}」
              </span>
            ) : beside ? (
              <span>另起 · 与「{short(beside.question, 20)}」同级</span>
            ) : parentNode ? (
              <span>追问 ›「{short(parentNode.question, 24)}」</span>
            ) : (
              <span>新话题</span>
            )}
            {target.anchor || beside ? (
              <button type="button" className="qa-link" onClick={() => (active ? focus(active) : newTopic())}>
                取消
              </button>
            ) : parentNode ? (
              <button type="button" className="qa-link" onClick={newTopic}>
                改为新话题
              </button>
            ) : (
              active && (
                <button type="button" className="qa-link" onClick={() => focus(active)}>
                  改为追问
                </button>
              )
            )}
          </div>
        )}
        <textarea
          ref={input}
          value={draft}
          rows={2}
          placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"
          aria-label="问题"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <div className="composer-foot">
          <span>只依据本文回答，并标出处</span>
          {running ? (
            <button type="button" className="send" aria-label="停止" title="停止" onClick={cancel}>
              <span className="stop-square" />
            </button>
          ) : (
            <button type="button" className="send" aria-label="发送" title="发送" disabled={!draft.trim()} onClick={send}>
              <Icon name="send" strokeWidth={2} />
            </button>
          )}
        </div>
      </div>
      <Dialog
        open={Boolean(doomed)}
        headline="删除这一支？"
        onClose={(v) => {
          if (v === "ok" && doomed) void removeNode(doomed.id);
          setDoomed(null);
        }}
        actions={[
          { value: "cancel", label: "取消" },
          { value: "ok", label: "删除", primary: true },
        ]}
      >
        {doomed && (
          <p>
            「{short(doomed.question, 40)}」
            {countBelow(tree.children, doomed.id)
              ? `和它下面的 ${countBelow(tree.children, doomed.id)} 轮追问都会删除，不能恢复。`
              : "这一轮会删除，不能恢复。"}
          </p>
        )}
      </Dialog>
    </aside>
  );
}

function countBelow(children: Map<string | null, QaNode[]>, id: string): number {
  let n = 0;
  const stack = [...(children.get(id) ?? [])];
  while (stack.length) {
    const c = stack.pop()!;
    n++;
    stack.push(...(children.get(c.id) ?? []));
  }
  return n;
}

function Quote({ text }: { text: string }) {
  return <div className="qa-quote">「{short(text, 80)}」</div>;
}

function Turn({
  node,
  enter,
  siblings,
  anchors,
  cited,
  running,
  blockText,
  onPick,
  onSwitch,
  onFollowUp,
  onRetake,
  onDiverge,
  onDelete,
}: {
  node: QaNode;
  enter: boolean;
  siblings: QaNode[];
  anchors: AnchorRange[];
  cited: string | null;
  running: boolean;
  blockText: (id: string) => string | undefined;
  onPick: (id: string) => void;
  onSwitch: (id: string) => void;
  onFollowUp: (id: string) => void;
  onRetake: (id: string) => void;
  onDiverge: (id: string) => void;
  onDelete: (node: QaNode) => void;
}) {
  const i = siblings.findIndex((s) => s.id === node.id);
  const anchor = anchorOf(node);
  return (
    <div className={`qa-turn${enter ? " enter" : ""}`}>
      {siblings.length > 1 && (
        <div className="qa-branch-switch" role="group" aria-label="同级分支">
          <button
            type="button"
            aria-label="上一个分支"
            disabled={i <= 0}
            onClick={() => onSwitch(siblings[i - 1].id)}
          >
            ‹
          </button>
          <span>
            {i + 1} / {siblings.length}
          </span>
          <button
            type="button"
            aria-label="下一个分支"
            disabled={i >= siblings.length - 1}
            onClick={() => onSwitch(siblings[i + 1].id)}
          >
            ›
          </button>
        </div>
      )}
      {anchor && <Quote text={anchor} />}
      <div className="qa-question">{node.question}</div>
      <div className={`qa-answer${node.untraced ? " untraced" : ""}`} data-node={node.id}>
        {node.untraced && (
          <span className="nofound">
            <Icon name="alert" size={14} strokeWidth={1.8} />
            未找到依据
          </span>
        )}
        <div>{renderAnswer(node.answer, anchors, cited, blockText, onPick, onSwitch)}</div>
      </div>
      {node.status === "stale" && <p className="search-note">原文已重新解析，部分引用已失效。</p>}
      <div className="qa-actions">
        <button type="button" className="qa-link" onClick={() => onFollowUp(node.id)}>
          追问
        </button>
        <button type="button" className="qa-link" disabled={running} onClick={() => onRetake(node.id)}>
          重答
        </button>
        <button type="button" className="qa-link" onClick={() => onDiverge(node.id)}>
          另起
        </button>
        <button type="button" className="qa-link danger" disabled={running} onClick={() => onDelete(node)}>
          删除分支
        </button>
      </div>
    </div>
  );
}

/** [b_0012] → 编号标签（同一答案内按首次出现编号）；子节点"就此追问"的选段加下划线，点它进入那一支。 */
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
        title="就此追问过：点击进入那一支"
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
