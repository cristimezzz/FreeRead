import type { Schemas } from "../../api/client";

type Item = Schemas["ItemOut"];

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

export function ItemList({ items, onOpen }: { items: Item[]; onOpen: (item: Item) => void }) {
  return (
    <div className="item-list" role="list">
      {items.map((it) => {
        const doc = it.documents.find((d) => d.parse_status === "ready") ?? it.documents[0];
        const meta = [formatAuthors(it.authors), it.year, it.venue].filter(Boolean).join(" · ");
        const status = doc?.parse_status ?? "pending";
        return (
          <button key={it.id} className="item-row" role="listitem" onClick={() => onOpen(it)}>
            <span className="item-title">{it.title || "（无标题）"}</span>
            <span className="item-status">
              {doc ? (
                <span className="chip" data-status={status}>
                  {STATUS_LABEL[status]}
                </span>
              ) : (
                <span className="chip">无 PDF</span>
              )}
            </span>
            <span className="item-meta">{meta}</span>
          </button>
        );
      })}
    </div>
  );
}
