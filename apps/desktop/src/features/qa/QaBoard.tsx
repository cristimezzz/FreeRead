// 全卡片式问答（docs/m3/qa-tree.md）：打开问答时铺满阅读区。每一问一答是一张卡片，按问答树排开；
// 收起的卡片只显示 AI 标题，点开后是完整问答、操作和输入框（追问它）。另起 / 新话题时出现一张草稿卡片。

import { useEffect, useMemo, useRef, useState } from "react";
import { ActionDialog, IconButton, OptionSelect } from "../../components/controls";
import { PanelNote } from "../../components/SidePanel";
import { Button } from "../../components/ui/button";
import { anchorRanges } from "./anchors";
import { QaCanvas } from "./QaCanvas";
import {
  anchorOf,
  CollapsedCard,
  Composer,
  DraftCard,
  ExpandedCard,
  PendingCard,
  short,
  titleOf,
} from "./QaCard";
import { buildTree, pathTo, type TreeItem } from "./tree";
import type { QaNode, useQa } from "./useQa";

interface Props {
  state: ReturnType<typeof useQa>;
  /** 引用块的原文（悬停提示用） */
  blockText: (id: string) => string | undefined;
  /** 点引用编号：收起问答、跳到原文 */
  onPick: (blockId: string) => void;
  onClose: () => void;
}

const NEW = "__new__";
const PENDING = "__pending__";
const DRAFT = "__draft__";

interface Item extends TreeItem {
  node?: QaNode;
}

export function QaBoard({ state, blockText, onPick, onClose }: Props) {
  const { sessions, current, nodes, tree, active, target, pending, running, error, lastModes } = state;
  const { select, ask, cancel, remove, focus, switchTo, diverge, retake, spawnFromSelection, newTopic, removeNode } =
    state;
  const [draft, setDraft] = useState("");
  const [cited, setCited] = useState<string | null>(null);
  const [fitKey, setFitKey] = useState(0);
  const [doomed, setDoomed] = useState<QaNode | null>(null);
  const [selPop, setSelPop] = useState<{ id: string; text: string; x: number; y: number } | null>(null);
  const board = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  // 草稿卡片：另起（与某张卡片同级）或新话题（新的根）；还没有任何卡片时也是它
  const drafting = !pending && (target.parentId === null || Boolean(target.besideId));
  const expanded = pending ? PENDING : drafting ? DRAFT : active;
  const base = pending ? pending.parentId : drafting ? target.parentId : active;

  const items = useMemo(() => {
    const list: Item[] = nodes.map((n) => ({ id: n.id, parent_id: n.parent_id, node: n }));
    if (pending) list.push({ id: PENDING, parent_id: pending.parentId });
    else if (drafting) list.push({ id: DRAFT, parent_id: target.parentId });
    return buildTree(list);
  }, [nodes, pending, drafting, target.parentId]);

  const onPath = useMemo(
    () => new Set([...pathTo(tree, base).map((n) => n.id), ...(pending ? [PENDING] : drafting ? [DRAFT] : [])]),
    [tree, base, pending, drafting],
  );

  // 打开 / 切换对话后把整棵树放进窗口
  const loaded = nodes.length > 0;
  useEffect(() => {
    setFitKey((k) => k + 1);
  }, [current, loaded]);

  const send = () => {
    if (!draft.trim() || running) return;
    void ask(draft);
    setDraft("");
  };

  const pick = (id: string) => {
    setCited(id);
    onPick(id);
  };

  // 在展开卡片的回答里选中文字：浮出"就此追问"
  const onSelect = () => {
    const sel = window.getSelection();
    const box = board.current;
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
    setSelPop({ id: a.dataset.node!, text: text.slice(0, 500), x: r.left + r.width / 2 - b.left, y: r.top - b.top });
  };

  const spawn = () => {
    if (!selPop) return;
    spawnFromSelection(selPop.id, selPop.text);
    setDraft(`「${short(selPop.text, 40)}」是什么意思？`);
    setSelPop(null);
    window.getSelection()?.removeAllRanges();
    input.current?.focus();
  };

  const composer = (label: string, aside?: { text: string; onClick: () => void }) => (
    <Composer
      label={label}
      aside={aside}
      draft={draft}
      setDraft={setDraft}
      running={running}
      onSend={send}
      onStop={cancel}
      inputRef={input}
    />
  );

  const renderCard = (item: Item, open: boolean) => {
    if (item.id === PENDING && pending) {
      return <PendingCard question={pending.question} anchor={pending.anchor} text={pending.text} onStop={cancel} />;
    }
    if (item.id === DRAFT) {
      const beside = target.besideId ? tree.byId.get(target.besideId) : undefined;
      const heading = beside ? `另起 · 与「${titleOf(beside)}」同级` : "新话题";
      const back = active ? { text: "取消", onClick: () => focus(active) } : undefined;
      return (
        <DraftCard
          heading={heading}
          composer={
            <Composer
              label={nodes.length ? (beside ? "与它同级的新问题" : "不接着任何卡片的新问题") : "就这篇论文提问"}
              aside={back}
              draft={draft}
              setDraft={setDraft}
              running={running}
              onSend={send}
              onStop={cancel}
              inputRef={input}
              autoFocus
            />
          }
        />
      );
    }
    const n = item.node!;
    if (!open) {
      return (
        <CollapsedCard
          title={titleOf(n)}
          full={n.question}
          anchored={Boolean(anchorOf(n))}
          active={n.id === active}
          onPath={onPath.has(n.id)}
          onOpen={() => focus(n.id)}
        />
      );
    }
    const childAnchors = (tree.children.get(n.id) ?? []).flatMap((c) =>
      anchorOf(c) ? [{ id: c.id, text: anchorOf(c)! }] : [],
    );
    return (
      <ExpandedCard
        node={n}
        anchors={anchorRanges(n.answer, childAnchors)}
        cited={cited}
        running={running}
        blockText={blockText}
        onPick={pick}
        onAnchor={switchTo}
        onRetake={() => retake(n.id)}
        onDiverge={() => diverge(n.id)}
        onDelete={() => setDoomed(n)}
        composer={
          target.anchor
            ? composer(`就此追问 ·「${short(target.anchor, 24)}」`, { text: "取消选段", onClick: () => focus(n.id) })
            : composer("追问这张卡片", { text: "改为新话题", onClick: newTopic })
        }
      />
    );
  };

  const noVector = lastModes && !lastModes.includes("vector");

  return (
    <div
      className="qa-board"
      ref={board}
      role="region"
      aria-label="问答"
      onMouseUp={onSelect}
      onKeyUp={(e) => e.shiftKey && onSelect()}
    >
      <div className="bg-card absolute top-3 left-3 z-3 flex max-w-[calc(100%-24px)] items-center gap-1 rounded-xl border py-1 pr-1.5 pl-3.5">
        <h2 className="mr-2 flex-none font-serif text-lg font-medium">问答</h2>
        <OptionSelect
          label="对话"
          hideLabel
          className="text-foreground/80 h-8 max-w-55 min-w-0 flex-1 border-transparent bg-transparent shadow-none"
          value={current ?? NEW}
          options={[
            ...(current ? [] : [{ value: NEW, label: "新对话" }]),
            ...sessions.map((s) => ({ value: s.id, label: s.title || "未命名对话" })),
          ]}
          onValue={(v) => void select(v === NEW ? null : v)}
        />
        <IconButton icon="add" label="新对话" disabled={!current} onClick={() => void select(null)} />
        <Button variant="ghost" size="sm" disabled={!nodes.length || running} onClick={newTopic}>
          新话题
        </Button>
        <IconButton icon="fit" label="适应窗口" disabled={!nodes.length} onClick={() => setFitKey((k) => k + 1)} />
        <IconButton
          icon="delete"
          label="删除对话"
          disabled={!current || running}
          onClick={() => current && void remove(current)}
        />
        <IconButton icon="close" label="关闭问答" onClick={onClose} />
      </div>

      <QaCanvas
        tree={items}
        expanded={expanded}
        onPath={onPath}
        renderCard={renderCard}
        fitKey={fitKey}
        onViewChange={() => selPop && setSelPop(null)}
      />

      <div className="pointer-events-none absolute bottom-3 left-3 z-2 flex max-w-[min(520px,calc(100%-24px))] flex-col gap-1.5 [&>p]:pointer-events-auto [&>p]:m-0 [&>p]:rounded-lg [&>p]:border [&>p]:bg-card [&>p]:px-3 [&>p]:py-2">
        {!nodes.length && !pending && (
          <PanelNote>
            就这篇论文提问，回答会标出依据的原文，点编号跳回原文。每张卡片都可以接着追问、重答或另起一张；选中回答里的文字可以就此追问。提问会把检索到的段落发送给问答所用的大模型服务（默认与总结相同）。
          </PanelNote>
        )}
        {noVector && (
          <PanelNote>
            这篇论文还没有语义索引，只按关键词找原文，回答可能不全。可在 设置 › 检索 中下载嵌入模型。
          </PanelNote>
        )}
        {error && <PanelNote error>{error}</PanelNote>}
      </div>

      {selPop && (
        <button
          type="button"
          className="bg-primary text-primary-foreground animate-in fade-in-0 absolute z-4 -translate-x-1/2 -translate-y-[calc(100%+6px)] cursor-pointer rounded-md px-2.5 py-1 text-xs whitespace-nowrap"
          style={{ left: selPop.x, top: selPop.y }}
          onMouseDown={(e) => e.preventDefault()}
          onMouseUp={(e) => e.stopPropagation()}
          onClick={spawn}
        >
          就此追问
        </button>
      )}

      <ActionDialog
        open={Boolean(doomed)}
        headline="删除这一支？"
        onClose={(v) => {
          if (v === "ok" && doomed) void removeNode(doomed.id);
          setDoomed(null);
        }}
        actions={[
          { value: "cancel", label: "取消" },
          { value: "ok", label: "删除", danger: true },
        ]}
      >
        {doomed && (
          <p>
            「{titleOf(doomed)}」
            {countBelow(tree.children, doomed.id)
              ? `和它下面的 ${countBelow(tree.children, doomed.id)} 张卡片都会删除，不能恢复。`
              : "这张卡片会删除，不能恢复。"}
          </p>
        )}
      </ActionDialog>
    </div>
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
