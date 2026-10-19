import { type ReactNode, useEffect, useRef, useState } from "react";
import { Icon } from "../../components/icons";
import { Select } from "../../components/md";
import type { QaNode, useQa } from "./useQa";

interface Props {
  state: ReturnType<typeof useQa>;
  /** 引用块的原文（悬停提示用） */
  blockText: (id: string) => string | undefined;
  onPick: (blockId: string) => void;
  onClose: () => void;
}

const NEW = "__new__";
// 流式原文里的引用标记（各种写法）：未校验，即时显示时先隐藏
const RAW_MARKER = /\s*[[【(（]\s*(?:d_[0-9a-f]+#)?b[_-]?\d+[^\]】)）]*[\]】)）]/gi;
// 校验后的答案只有 [b_0012] 一种写法
const MARKER = /\[(b_\d+)\]/g;
// 流式文本末尾还没写完的标记（如 "[b_00"）
const TRAILING_PARTIAL = /\s*[[【(（][^\]】)）]{0,24}$/;

export function QaPanel({ state, blockText, onPick, onClose }: Props) {
  const { sessions, current, nodes, pending, running, error, lastModes, select, ask, cancel, remove } = state;
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);

  // 新内容出现时滚到底部
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight });
  }, [nodes.length, pending?.text]);

  const send = () => {
    if (!draft.trim() || running) return;
    void ask(draft);
    setDraft("");
  };

  const pick = (id: string) => {
    setActive(id);
    onPick(id);
  };

  const noVector = lastModes && !lastModes.includes("vector");

  return (
    <aside className="side-panel qa-panel" aria-label="问答">
      <div className="side-panel-head">
        <h2>问答</h2>
        <span style={{ flex: 1 }} />
        <md-icon-button aria-label="关闭问答" onClick={onClose}>
          <Icon name="close" size={20} />
        </md-icon-button>
      </div>
      <div className="summary-controls">
        <Select
          label="对话"
          value={current ?? NEW}
          options={[
            ...(current ? [] : [{ value: NEW, label: "新对话" }]),
            ...sessions.map((s) => ({ value: s.id, label: s.title || "未命名对话" })),
          ]}
          onValue={(v) => void select(v === NEW ? null : v)}
        />
        <md-icon-button aria-label="新对话" title="新对话" disabled={!current || undefined} onClick={() => void select(null)}>
          <Icon name="add" size={20} />
        </md-icon-button>
        <md-icon-button
          aria-label="删除对话"
          title="删除对话"
          disabled={!current || running || undefined}
          onClick={() => current && void remove(current)}
        >
          <Icon name="delete" size={20} />
        </md-icon-button>
      </div>

      <div className="qa-messages" ref={list}>
        {!nodes.length && !pending && (
          <p className="search-note">
            就这篇论文提问，回答会标出依据的原文，点编号可以跳回原文。提问会把检索到的段落发送给问答所用的大模型服务（默认与总结相同）。
          </p>
        )}
        {nodes.map((n) => (
          <Turn key={n.id} node={n} active={active} blockText={blockText} onPick={pick} />
        ))}
        {pending && (
          <div className="qa-turn">
            <div className="qa-question">{pending.question}</div>
            <div className="qa-answer">
              {pending.text ? pending.text.replace(RAW_MARKER, "").replace(TRAILING_PARTIAL, "") : <span className="search-note">正在检索原文…</span>}
            </div>
          </div>
        )}
        {error && <p className="search-note error">{error}</p>}
      </div>

      {noVector && (
        <p className="search-note">
          这篇论文还没有语义索引，只按关键词找原文，回答可能不全。可在 设置 › 检索 中下载嵌入模型。
        </p>
      )}
      <div className="qa-input">
        <textarea
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
        {running ? (
          <md-text-button onClick={cancel}>停止</md-text-button>
        ) : (
          <md-filled-tonal-button disabled={!draft.trim() || undefined} onClick={send}>
            发送
          </md-filled-tonal-button>
        )}
      </div>
    </aside>
  );
}

function Turn({
  node,
  active,
  blockText,
  onPick,
}: {
  node: QaNode;
  active: string | null;
  blockText: (id: string) => string | undefined;
  onPick: (id: string) => void;
}) {
  return (
    <div className="qa-turn">
      <div className="qa-question">{node.question}</div>
      <div className={`qa-answer${node.untraced ? " untraced" : ""}`}>
        {renderAnswer(node.answer, active, blockText, onPick)}
        {node.untraced && <span className="untraced-tag">未找到依据</span>}
      </div>
      {node.status === "stale" && <p className="search-note">原文已重新解析，部分引用已失效。</p>}
    </div>
  );
}

/** [b_0012] → 编号标签；同一答案内按首次出现编号。 */
function renderAnswer(
  text: string,
  active: string | null,
  blockText: (id: string) => string | undefined,
  onPick: (id: string) => void,
): ReactNode[] {
  const numbers = new Map<string, number>();
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(MARKER)) {
    const id = m[1];
    out.push(text.slice(last, m.index));
    if (!numbers.has(id)) numbers.set(id, numbers.size + 1);
    out.push(
      <button
        key={`${m.index}-${id}`}
        className={`cite${id === active ? " active" : ""}`}
        title={blockText(id)?.slice(0, 200)}
        onClick={() => onPick(id)}
      >
        {numbers.get(id)}
      </button>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}
