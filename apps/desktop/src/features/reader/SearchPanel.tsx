import { type ReactNode, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { Icon } from "../../components/icons";

type Hit = Schemas["SearchHit"];
type Response = Schemas["SearchResponse"];

// 命中词在片段里用 STX / ETX 包起来（core/freeread/infra/search/fts.py）
const HL = /\x02(.*?)\x03/gs;

const TYPE_LABEL: Record<string, string> = {
  title: "标题",
  abstract: "摘要",
  paragraph: "正文",
  list_item: "列表",
  caption: "图表说明",
  footnote: "脚注",
  table: "表格",
};

interface Props {
  docId: string;
  embedStatus: string | undefined;
  onPick: (blockId: string) => void;
  onClose: () => void;
}

export function SearchPanel({ docId, embedStatus, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Response | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  useEffect(() => input.current?.focus(), []);

  useEffect(() => {
    const q = query.trim();
    const n = ++seq.current;
    if (!q) {
      setResult(null);
      setError(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = unwrap(
          await api().GET("/documents/{doc_id}/search", {
            params: { path: { doc_id: docId }, query: { q, k: 30 } },
          }),
        );
        if (n === seq.current) {
          setResult(r);
          setError(null);
        }
      } catch (e) {
        if (n === seq.current) setError(String(e));
      }
    }, 250);
    return () => clearTimeout(t);
    // embedStatus 变了（嵌入完成）时重新搜索，结果会带上语义命中
  }, [query, docId, embedStatus]);

  const pick = (h: Hit) => {
    setActive(h.block_id);
    onPick(h.block_id);
  };

  const semantic = result?.modes.includes("vector");
  const note =
    result && !semantic
      ? embedStatus === "embedding" || embedStatus === "pending"
        ? "语义索引还在建立，目前只按关键词匹配"
        : "语义检索未启用（可在 设置 › 检索 中开启），目前只按关键词匹配"
      : null;

  return (
    <aside className="search-panel" aria-label="文内搜索">
      <div className="search-box">
        <Icon name="search" size={20} />
        <input
          ref={input}
          type="search"
          value={query}
          placeholder="搜索关键词或提一个问题"
          aria-label="搜索本文"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "Enter" && result?.hits[0]) pick(result.hits[0]);
          }}
        />
        <md-icon-button aria-label="关闭搜索" onClick={onClose}>
          <Icon name="close" size={20} />
        </md-icon-button>
      </div>
      {note && <p className="search-note">{note}</p>}
      {error && <p className="search-note error">搜索失败：{error}</p>}
      {result && !result.hits.length && <p className="search-note">没有找到相关内容</p>}
      <ol className="search-hits">
        {result?.hits.map((h) => (
          <li key={h.block_id}>
            <button className={h.block_id === active ? "active" : undefined} onClick={() => pick(h)}>
              <span className="search-meta">
                {TYPE_LABEL[h.type] ?? h.type}
                {h.page != null && ` · 第 ${h.page + 1} 页`}
                {h.sources.includes("vector") && !h.sources.includes("fts") && " · 语义相关"}
              </span>
              <span className="search-snippet">{renderSnippet(h.snippet)}</span>
            </button>
          </li>
        ))}
      </ol>
    </aside>
  );
}

function renderSnippet(s: string) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of s.matchAll(HL)) {
    out.push(s.slice(last, m.index));
    out.push(<mark key={m.index}>{m[1]}</mark>);
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(s.slice(last));
  return out;
}
