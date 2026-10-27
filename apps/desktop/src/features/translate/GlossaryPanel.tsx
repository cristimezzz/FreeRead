import { type ReactNode, useState } from "react";
import { IconButton, ProgressBar } from "../../components/controls";
import { Icon } from "../../components/icons";
import { PanelFoot, PanelNote, SidePanel } from "../../components/SidePanel";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import type { Term, useGlossary } from "./useGlossary";

interface Props {
  state: ReturnType<typeof useGlossary>;
  onClose?: () => void;
  /** 设置页里只管理全局条目：没有抽取按钮和"提升为全局" */
  globalOnly?: boolean;
}

interface Draft {
  source: string;
  target: string;
  note: string;
}

const EMPTY: Draft = { source: "", target: "", note: "" };

function TermForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: Draft;
  submitLabel: string;
  onSubmit: (d: Draft) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [d, setD] = useState(initial);
  const [busy, setBusy] = useState(false);
  const ok = d.source.trim() && d.target.trim();
  const submit = async () => {
    if (!ok || busy) return;
    setBusy(true);
    try {
      await onSubmit(d);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="grid grid-cols-2 gap-2 border-b py-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}
    >
      <Input
        className="h-8 min-w-0"
        aria-label="原文术语"
        placeholder="原文术语"
        autoFocus
        value={d.source}
        onChange={(e) => setD({ ...d, source: e.target.value })}
      />
      <Input
        className="h-8 min-w-0"
        aria-label="译法"
        placeholder="译法"
        value={d.target}
        onChange={(e) => setD({ ...d, target: e.target.value })}
      />
      <Input
        className="col-span-full h-8 min-w-0"
        aria-label="说明（可选）"
        placeholder="说明（可选）"
        value={d.note}
        onChange={(e) => setD({ ...d, note: e.target.value })}
      />
      <div className="col-span-full flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button size="sm" type="submit" disabled={!ok || busy}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

export function GlossaryPanel({ state, onClose, globalOnly }: Props) {
  const { terms, loaded, job, extracting, add, update, remove, extract } = state;
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const q = filter.trim().toLowerCase();
  const shown = q
    ? terms.filter((t) => t.source.toLowerCase().includes(q) || t.target.toLowerCase().includes(q))
    : terms;
  const docTerms = shown.filter((t) => t.scope !== "global");
  const globalTerms = shown.filter((t) => t.scope === "global");

  const row = (t: Term) =>
    editing === t.id ? (
      <li key={t.id}>
        <TermForm
          initial={{ source: t.source, target: t.target, note: t.note }}
          submitLabel="保存"
          onCancel={() => setEditing(null)}
          onSubmit={async (d) => {
            if (await update(t.id, { source: d.source, target: d.target, note: d.note })) setEditing(null);
          }}
        />
      </li>
    ) : (
      <li key={t.id} className="group/term flex items-start gap-2 border-b py-2">
        <div className="min-w-0 flex-1 text-[13.5px] leading-relaxed wrap-anywhere">
          <span>{t.source}</span>
          <span className="text-muted-foreground mx-1.5" aria-hidden>
            →
          </span>
          <span className="text-foreground/80">{t.target}</span>
          {t.origin === "auto" && (
            <Badge variant="secondary" className="bg-brand-soft text-brand ml-2 px-1.5 py-0 text-[11px] font-normal">
              自动
            </Badge>
          )}
          {t.note && <div className="text-muted-foreground text-xs">{t.note}</div>}
        </div>
        <div className="flex flex-none opacity-55 transition-opacity group-focus-within/term:opacity-100 group-hover/term:opacity-100">
          <IconButton icon="edit" label="编辑" onClick={() => setEditing(t.id)} />
          {!globalOnly && t.scope !== "global" && (
            <IconButton icon="all" label="提升为全局（对所有文档生效）" onClick={() => void update(t.id, { scope: "global" })} />
          )}
          <IconButton icon="delete" label="删除" onClick={() => void remove(t.id)} />
        </div>
      </li>
    );

  return (
    <Shell globalOnly={globalOnly} onClose={onClose}>
      <div className={cn("flex items-end gap-2", globalOnly ? "pb-2" : "px-6 pb-2")}>
        <Input
          className="h-8 min-w-0 flex-1"
          aria-label="筛选术语"
          placeholder="筛选"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {!globalOnly && (
          <Button variant="outline" size="sm" disabled={extracting} onClick={() => void extract()}>
            <Icon name="sync" />
            {terms.some((t) => t.origin === "auto" && t.scope !== "global") ? "重新抽取" : "自动抽取"}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => setAdding(true)} disabled={adding}>
          <Icon name="add" />
          添加
        </Button>
      </div>
      {extracting && (
        <div className="text-muted-foreground mx-6 mt-2 mb-1 flex flex-col gap-2 text-xs">
          <ProgressBar />
          <span>{job?.status === "queued" ? "等待抽取…" : "正在从论文中抽取术语…"}</span>
        </div>
      )}
      {job?.status === "failed" && !extracting && <PanelNote error>抽取失败：{job.error}</PanelNote>}
      <div className={cn(!globalOnly && "min-h-0 flex-1 overflow-auto px-6 pt-1 pb-6")}>
        {adding && (
          <TermForm
            initial={EMPTY}
            submitLabel="添加"
            onCancel={() => setAdding(false)}
            onSubmit={async (d) => {
              if (await add(d.source, d.target, d.note, globalOnly)) setAdding(false);
            }}
          />
        )}
        {loaded && !terms.length && !adding && (
          <PanelNote className={cn(globalOnly && "mx-0")}>
            {globalOnly
              ? "还没有全局术语。可以在这里添加，或在阅读器的术语表里把文档术语提升为全局。"
              : "还没有术语。可以让模型从论文中自动抽取，或手动添加；翻译时只会带上段落里出现的术语。"}
          </PanelNote>
        )}
        {!globalOnly && docTerms.length > 0 && (
          <>
            <h3 className={SUBHEAD}>本文术语</h3>
            <ul>{docTerms.map(row)}</ul>
          </>
        )}
        {globalTerms.length > 0 && (
          <>
            {!globalOnly && <h3 className={SUBHEAD}>全局术语</h3>}
            <ul>{globalTerms.map(row)}</ul>
          </>
        )}
      </div>
      {!globalOnly && terms.length > 0 && (
        <PanelFoot>修改术语后，已有译文不会自动更新；新翻译的段落按新术语翻译。</PanelFoot>
      )}
    </Shell>
  );
}

const SUBHEAD = "text-muted-foreground mt-4.5 mb-1.5 text-xs font-semibold tracking-wider";

/** 阅读器里是带标题的侧边面板；设置页里（globalOnly）直接嵌在分组里。 */
function Shell({ globalOnly, onClose, children }: { globalOnly?: boolean; onClose?: () => void; children: ReactNode }) {
  if (globalOnly) return <div aria-label="术语表">{children}</div>;
  return (
    <SidePanel
      title="术语表"
      aria-label="术语表"
      actions={onClose && <IconButton icon="close" label="关闭术语表" onClick={onClose} />}
    >
      {children}
    </SidePanel>
  );
}
