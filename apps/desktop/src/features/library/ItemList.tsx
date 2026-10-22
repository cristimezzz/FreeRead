import type { Schemas } from "../../api/client";

type Item = Schemas["ItemOut"];
type Doc = Schemas["DocRef"];

const STATUS_LABEL: Record<string, string> = {
  pending: "待解析",
  parsing: "解析中",
  ready: "可阅读",
  failed: "解析失败",
};

export function formatAuthors(authors: Item["authors"]): string {
  const names = authors
    .filter((a) => (a.type ?? "author") === "author")
    .map((a) => (a.name as string | undefined) || [a.last, a.first].filter(Boolean).join(", "));
  if (names.length > 3) return `${names.slice(0, 3).join("; ")} 等`;
  return names.join("; ");
}

/** 点条目本身时打开的 PDF：优先本地文件还在且已解析的，其次文件还在的。 */
export function defaultDoc(item: Item): Doc | undefined {
  const present = item.documents.filter((d) => d.file_exists && d.doc_id);
  return present.find((d) => d.parse_status === "ready") ?? present[0];
}

interface ItemListProps {
  items: Item[];
  onOpen: (item: Item, doc?: Doc) => void;
  /** 当前选中的条目（键盘操作、右键菜单的对象） */
  selectedId?: string | null;
  onSelect?: (item: Item) => void;
  /** 右键（或菜单键 / Shift+F10）：在视口坐标 (x, y) 为该条目弹出菜单 */
  onMenu?: (item: Item, x: number, y: number) => void;
  /** 批量选中的条目；传了 onCheck 才显示复选框 */
  checked?: ReadonlySet<string>;
  /** 勾选 / 取消勾选；range 为 true（Shift）时从上一次勾选的条目连选到这里 */
  onCheck?: (item: Item, range: boolean) => void;
}

export function ItemList({ items, onOpen, selectedId, onSelect, onMenu, checked, onCheck }: ItemListProps) {
  return (
    <div
      className="item-list"
      role="list"
      data-checkable={onCheck ? true : undefined}
      data-checking={checked?.size ? true : undefined}
    >
      {items.map((it) => {
        const doc = defaultDoc(it);
        const meta = [formatAuthors(it.authors), it.year, it.venue].filter(Boolean).join(" · ");
        const status = doc ? (doc.parse_status ?? "pending") : "none";
        const selected = it.id === selectedId;
        const isChecked = !!checked?.has(it.id);
        return (
          <div
            key={it.id}
            className="item"
            role="listitem"
            data-selected={selected || undefined}
            data-checked={isChecked || undefined}
            onContextMenu={(e) => {
              if (!onMenu) return;
              e.preventDefault();
              onSelect?.(it);
              // 键盘触发的 contextmenu 坐标可能落在别处：不在本条目内时贴着条目左下角弹出
              const r = e.currentTarget.getBoundingClientRect();
              const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
              onMenu(it, inside ? e.clientX : r.left + 16, inside ? e.clientY : r.bottom);
            }}
          >
            {onCheck && (
              <input
                type="checkbox"
                className="item-check"
                checked={isChecked}
                readOnly
                // 键盘用空格勾选当前条目，复选框本身不进 Tab 顺序
                tabIndex={-1}
                aria-label={`选择「${it.title || "无标题"}」`}
                onClick={(e) => onCheck(it, e.shiftKey)}
              />
            )}
            <button
              type="button"
              className="item-row"
              data-item-id={it.id}
              aria-current={selected || undefined}
              // 只有选中项可 Tab 进入，其余用方向键移动（没有选中项时第一项可进入）
              tabIndex={selected || (!selectedId && it === items[0]) ? 0 : -1}
              onFocus={() => onSelect?.(it)}
              // Shift 连选时别顺带选中一片文字
              onMouseDown={(e) => {
                if (e.shiftKey && onCheck) e.preventDefault();
              }}
              onClick={(e) => {
                // Ctrl / ⌘ 点击勾选，Shift 点击连选；普通点击始终是打开
                if (onCheck && (e.ctrlKey || e.metaKey || e.shiftKey)) onCheck(it, e.shiftKey);
                else onOpen(it);
              }}
            >
              <span className="item-text">
                <span className="item-title serif">{it.title || "（无标题）"}</span>
                {meta && <span className="item-meta">{meta}</span>}
              </span>
              <span className="tag" data-status={status}>
                <span className="dot" />
                {doc ? STATUS_LABEL[status] : "无 PDF"}
              </span>
            </button>
            {it.documents.length > 1 && (
              <div className="item-docs" aria-label="PDF 附件">
                {it.documents.map((d) => {
                  const s = d.file_exists ? (d.parse_status ?? "pending") : "none";
                  return (
                    <button
                      key={d.attachment_id}
                      type="button"
                      className="tag item-doc"
                      data-status={s}
                      disabled={!d.file_exists || !d.doc_id}
                      title={d.file_exists ? `${d.filename} · ${STATUS_LABEL[s]}` : `${d.filename} · 文件已不存在，重新同步后移除`}
                      onClick={() => onOpen(it, d)}
                    >
                      <span className="dot" />
                      <span className="item-doc-name">{d.filename}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
