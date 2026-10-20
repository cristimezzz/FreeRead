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

export function ItemList({ items, onOpen }: { items: Item[]; onOpen: (item: Item, doc?: Doc) => void }) {
  return (
    <div className="item-list" role="list">
      {items.map((it) => {
        const doc = defaultDoc(it);
        const meta = [formatAuthors(it.authors), it.year, it.venue].filter(Boolean).join(" · ");
        const status = doc ? (doc.parse_status ?? "pending") : "none";
        return (
          <div key={it.id} className="item" role="listitem">
            <button type="button" className="item-row" onClick={() => onOpen(it)}>
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
