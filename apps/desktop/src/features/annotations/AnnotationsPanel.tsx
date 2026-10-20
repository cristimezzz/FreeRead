import { useEffect, useRef, useState } from "react";
import { Button, IconButton } from "../../components/ui";
import { type Annotation, COLORS, type useAnnotations } from "./useAnnotations";

interface Props {
  state: ReturnType<typeof useAnnotations>;
  /** 渲染批注引文（占位符换成可读文本） */
  quoteText: (a: Annotation) => string;
  /** 刚点过的高亮：滚动到它并聚焦批注输入框 */
  focusId: string | null;
  onPick: (blockId: string) => void;
  onExport: () => void;
  onClose: () => void;
}

function NoteEditor({ a, autoFocus, onSave }: { a: Annotation; autoFocus: boolean; onSave: (note: string) => void }) {
  const [draft, setDraft] = useState(a.note);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => setDraft(a.note), [a.note]);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  return (
    <textarea
      ref={ref}
      className="ann-note"
      aria-label="批注"
      placeholder="写点批注…"
      rows={Math.min(8, Math.max(1, draft.split("\n").length))}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft !== a.note && onSave(draft)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) e.currentTarget.blur();
      }}
    />
  );
}

export function AnnotationsPanel({ state, quoteText, focusId, onPick, onExport, onClose }: Props) {
  const { items, update, remove } = state;
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!focusId) return;
    list.current?.querySelector(`[data-ann="${focusId}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusId]);

  return (
    <aside className="side-panel ann-panel" aria-label="批注">
      <div className="side-panel-head">
        <h2 className="serif">批注</h2>
        <Button small variant="ghost" icon="upload" onClick={onExport}>
          导出
        </Button>
        <IconButton icon="close" label="关闭批注" onClick={onClose} />
      </div>
      {!items.length && (
        <p className="search-note">在重排视图里选中原文，就可以用颜色高亮或写批注。批注只保存在本机，可以导出为 Markdown。</p>
      )}
      <ul className="ann-list" ref={list}>
        {items.map((a) => (
          <li key={a.id} className="ann-item" data-ann={a.id} data-active={a.id === focusId || undefined}>
            <button type="button" className="ann-quote" data-color={a.color} onClick={() => onPick(a.block_id)}>
              {quoteText(a) || "（整块）"}
            </button>
            {a.status === "stale" && <p className="search-note">原文已重新解析，找不到这段文字了。</p>}
            <NoteEditor a={a} autoFocus={a.id === focusId} onSave={(note) => void update(a.id, { note })} />
            <div className="ann-tools">
              {COLORS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  className="sel-color sm"
                  data-color={c.value}
                  aria-label={`改为${c.label}色`}
                  aria-pressed={a.color === c.value}
                  title={`改为${c.label}色`}
                  onClick={() => void update(a.id, { color: c.value })}
                />
              ))}
              <span className="ann-spacer" />
              <IconButton icon="delete" label="删除批注" onClick={() => void remove(a.id)} />
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
