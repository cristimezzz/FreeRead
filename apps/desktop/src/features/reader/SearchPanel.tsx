import { type ReactNode, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { Icon } from "../../components/icons";
import { IconButton } from "../../components/controls";
import { PanelNote, SidePanel } from "../../components/SidePanel";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";

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
    <SidePanel
      title="搜索"
      aria-label="文内搜索"
      actions={<IconButton icon="close" label="关闭搜索" onClick={onClose} />}
    >
      <div className="relative mr-4 mb-3 ml-6">
        <Icon name="search" className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 -translate-y-1/2" />
        <Input
          ref={input}
          type="search"
          className="pl-9"
          value={query}
          placeholder="搜索关键词或提一个问题"
          aria-label="搜索本文"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "Enter" && result?.hits[0]) pick(result.hits[0]);
          }}
        />
      </div>
      {note && <PanelNote>{note}</PanelNote>}
      {error && <PanelNote error>搜索失败：{error}</PanelNote>}
      {result && !result.hits.length && <PanelNote>没有找到相关内容</PanelNote>}
      <ol className="min-h-0 flex-1 overflow-auto px-3 pb-4">
        {result?.hits.map((h) => (
          <li key={h.block_id} className="animate-in fade-in-0">
            <button
              type="button"
              className={cn(
                "hover:bg-accent flex w-full cursor-pointer flex-col gap-1 rounded-lg px-3 py-2.5 text-left",
                h.block_id === active && "bg-brand-soft hover:bg-brand-soft",
              )}
              onClick={() => pick(h)}
            >
              <span className="text-muted-foreground text-[11.5px]">
                {TYPE_LABEL[h.type] ?? h.type}
                {h.page != null && ` · 第 ${h.page + 1} 页`}
                {h.sources.includes("vector") && !h.sources.includes("fts") && " · 语义相关"}
              </span>
              <span className="font-serif text-sm leading-relaxed">{renderSnippet(h.snippet)}</span>
            </button>
          </li>
        ))}
      </ol>
    </SidePanel>
  );
}

function renderSnippet(s: string) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of s.matchAll(HL)) {
    out.push(s.slice(last, m.index));
    out.push(
      <mark key={m.index} className="bg-brand-soft text-brand-ink rounded-[3px]">
        {m[1]}
      </mark>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(s.slice(last));
  return out;
}
