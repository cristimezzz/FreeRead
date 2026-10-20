import { useState } from "react";
import { Button, IconButton, Progress } from "../../components/ui";
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
      className="gl-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}
    >
      <input
        className="inp"
        aria-label="原文术语"
        placeholder="原文术语"
        autoFocus
        value={d.source}
        onChange={(e) => setD({ ...d, source: e.target.value })}
      />
      <input
        className="inp"
        aria-label="译法"
        placeholder="译法"
        value={d.target}
        onChange={(e) => setD({ ...d, target: e.target.value })}
      />
      <input
        className="inp gl-note"
        aria-label="说明（可选）"
        placeholder="说明（可选）"
        value={d.note}
        onChange={(e) => setD({ ...d, note: e.target.value })}
      />
      <div className="gl-form-actions">
        <Button small variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button small variant="primary" type="submit" disabled={!ok || busy}>
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
      <li key={t.id} className="gl-term">
        <div className="gl-text">
          <span className="gl-src">{t.source}</span>
          <span className="gl-arrow" aria-hidden>
            →
          </span>
          <span className="gl-tgt">{t.target}</span>
          {t.origin === "auto" && <span className="gl-badge">自动</span>}
          {t.note && <div className="gl-note-text">{t.note}</div>}
        </div>
        <div className="gl-actions">
          <IconButton icon="edit" label="编辑" onClick={() => setEditing(t.id)} />
          {!globalOnly && t.scope !== "global" && (
            <IconButton icon="all" label="提升为全局（对所有文档生效）" onClick={() => void update(t.id, { scope: "global" })} />
          )}
          <IconButton icon="delete" label="删除" onClick={() => void remove(t.id)} />
        </div>
      </li>
    );

  return (
    <aside className={globalOnly ? "gl-panel gl-inline" : "side-panel gl-panel"} aria-label="术语表">
      {!globalOnly && (
        <div className="side-panel-head">
          <h2 className="serif">术语表</h2>
          {onClose && <IconButton icon="close" label="关闭术语表" onClick={onClose} />}
        </div>
      )}
      <div className="summary-controls">
        <input
          className="inp gl-filter"
          aria-label="筛选术语"
          placeholder="筛选"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {!globalOnly && (
          <Button small icon="sync" disabled={extracting} onClick={() => void extract()}>
            {terms.some((t) => t.origin === "auto" && t.scope !== "global") ? "重新抽取" : "自动抽取"}
          </Button>
        )}
        <Button small icon="add" onClick={() => setAdding(true)} disabled={adding}>
          添加
        </Button>
      </div>
      {extracting && (
        <div className="summary-progress">
          <Progress />
          <span>{job?.status === "queued" ? "等待抽取…" : "正在从论文中抽取术语…"}</span>
        </div>
      )}
      {job?.status === "failed" && !extracting && <p className="search-note error">抽取失败：{job.error}</p>}
      <div className="gl-body">
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
          <p className="search-note">
            {globalOnly
              ? "还没有全局术语。可以在这里添加，或在阅读器的术语表里把文档术语提升为全局。"
              : "还没有术语。可以让模型从论文中自动抽取，或手动添加；翻译时只会带上段落里出现的术语。"}
          </p>
        )}
        {!globalOnly && docTerms.length > 0 && (
          <>
            <h3>本文术语</h3>
            <ul className="gl-list">{docTerms.map(row)}</ul>
          </>
        )}
        {globalTerms.length > 0 && (
          <>
            {!globalOnly && <h3>全局术语</h3>}
            <ul className="gl-list">{globalTerms.map(row)}</ul>
          </>
        )}
      </div>
      {!globalOnly && terms.length > 0 && (
        <div className="panel-foot">修改术语后，已有译文不会自动更新；新翻译的段落按新术语翻译。</div>
      )}
    </aside>
  );
}
