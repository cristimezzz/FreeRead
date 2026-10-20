import { useMemo, useState } from "react";
import { Button, IconButton, Progress, Select } from "../../components/ui";
import {
  ENTITY_TYPES,
  RELATION_LABEL,
  typeLabel,
  type KgEntity,
  type KgEntityType,
  type KgRelation,
  type KgSuggestion,
  type useKg,
} from "./useKg";

interface Props {
  state: ReturnType<typeof useKg>;
  blockText?: (id: string) => string | undefined;
  onPick: (blockId: string) => void;
  onClose: () => void;
}

type Filter = KgEntityType | "all";

function formatValue(r: KgRelation): string {
  const a = r.attrs as { metric?: string; value_text?: string; value?: number; unit?: string };
  const v = a.value_text ?? (a.value != null ? String(a.value) : "");
  return `${a.metric ?? r.dst_name} = ${v}${a.unit ? ` ${a.unit}` : ""}`;
}

/** 出处块按阅读顺序编号（b_0000 显示为 1），悬停看原文。 */
function Cite({
  id,
  blockText,
  onPick,
}: {
  id: string;
  blockText?: (id: string) => string | undefined;
  onPick: (id: string) => void;
}) {
  return (
    <button type="button" className="cite" title={blockText?.(id)} onClick={() => onPick(id)}>
      {Number(id.replace(/\D/g, "")) + 1}
    </button>
  );
}

/** 一条关系：在实体下面写成"类型 另一端"，指向它的写成"来源 类型 它的名字"；数值结果单独列出。 */
function RelationLine({
  r,
  self,
  blockText,
  onPick,
  onReject,
}: {
  r: KgRelation;
  self?: string;
  blockText?: (id: string) => string | undefined;
  onPick: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const outgoing = r.src_id === self;
  const label = RELATION_LABEL[r.type] ?? r.type;
  return (
    <li className="kg-rel" data-status={r.status}>
      <span className="kg-rel-text" title={r.evidence || undefined}>
        {self ? (
          outgoing ? (
            <>
              <span className="kg-rel-type">{label}</span> {r.type === "achieves" ? formatValue(r) : r.dst_name}
            </>
          ) : (
            <>
              <span className="kg-rel-other">{r.src_name}</span> <span className="kg-rel-type">{label}</span>{" "}
              {r.dst_name}
            </>
          )
        ) : (
          <>
            <span className="kg-rel-other">{r.src_name}</span> · {formatValue(r)}
          </>
        )}
        {typeof r.attrs.dataset === "string" && r.type === "achieves" && (
          <span className="kg-rel-dim">（{r.attrs.dataset}）</span>
        )}
        <Cite id={r.block_id} blockText={blockText} onPick={onPick} />
        {r.status === "stale" && <span className="gl-badge kg-stale">出处已失效</span>}
      </span>
      <IconButton icon="delete" label="删除这条关系（重新抽取不会加回）" onClick={() => onReject(r.id)} />
    </li>
  );
}

function MergePicker({
  entity,
  state,
  onDone,
}: {
  entity: KgEntity;
  state: Props["state"];
  onDone: () => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<KgEntity[] | null>(null);
  const find = async () => {
    const list = await state.search(q.trim(), entity.type as KgEntityType);
    setResults(list.filter((e) => e.id !== entity.id));
  };
  return (
    <div className="kg-edit">
      <form
        className="kg-edit-row"
        onSubmit={(e) => {
          e.preventDefault();
          void find();
        }}
      >
        <input
          className="inp"
          aria-label="要合并到的实体"
          placeholder={`搜索同类${typeLabel(entity.type)}`}
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onDone()}
        />
        <Button small type="submit">
          搜索
        </Button>
        <Button small variant="ghost" onClick={onDone}>
          取消
        </Button>
      </form>
      {results && !results.length && <p className="search-note">没有找到同类实体。</p>}
      {results && results.length > 0 && (
        <ul className="kg-pick">
          {results.map((e) => (
            <li key={e.id}>
              <span>
                {e.name}
                {e.aliases.length > 0 && <span className="kg-alias">（{e.aliases.join("、")}）</span>}
                <span className="kg-rel-dim"> · {e.doc_count} 篇</span>
              </span>
              <Button
                small
                onClick={async () => {
                  if (await state.merge(e.id, entity.id)) onDone();
                }}
              >
                并入
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SplitPicker({ entity, state, onDone }: { entity: KgEntity; state: Props["state"]; onDone: () => void }) {
  const names = [entity.name, ...entity.aliases];
  const [picked, setPicked] = useState<string[]>([]);
  const ok = picked.length > 0 && picked.length < names.length;
  return (
    <div className="kg-edit">
      <p className="search-note">勾选不属于"{entity.name}"的写法，拆成一个新实体：</p>
      <div className="kg-split">
        {names.map((n) => (
          <label key={n}>
            <input
              type="checkbox"
              checked={picked.includes(n)}
              onChange={(e) => setPicked(e.target.checked ? [...picked, n] : picked.filter((p) => p !== n))}
            />
            {n}
          </label>
        ))}
      </div>
      <div className="gl-form-actions">
        <Button small variant="ghost" onClick={onDone}>
          取消
        </Button>
        <Button
          small
          variant="primary"
          disabled={!ok}
          onClick={async () => {
            if (await state.split(entity.id, picked)) onDone();
          }}
        >
          拆分
        </Button>
      </div>
    </div>
  );
}

function EntityItem({
  e,
  relations,
  state,
  blockText,
  onPick,
}: {
  e: KgEntity;
  relations: KgRelation[];
  state: Props["state"];
  blockText?: (id: string) => string | undefined;
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"rename" | "merge" | "split" | null>(null);
  const [name, setName] = useState(e.name);
  const mine = relations.filter((r) => r.src_id === e.id || r.dst_id === e.id);
  return (
    <li className="kg-entity" data-open={open || undefined}>
      <div className="kg-head">
        <button type="button" className="kg-name" aria-expanded={open} onClick={() => setOpen(!open)}>
          {e.name}
          {e.aliases.length > 0 && <span className="kg-alias">（{e.aliases.join("、")}）</span>}
        </button>
        {e.doc_count > 1 && (
          <span className="gl-badge" title="这个实体也出现在其他文献里">
            {e.doc_count} 篇
          </span>
        )}
        {e.origin === "user" && <span className="gl-badge kg-user">已编辑</span>}
        <span className="kg-cites">
          {e.block_ids.slice(0, 4).map((id) => (
            <Cite key={id} id={id} blockText={blockText} onPick={onPick} />
          ))}
          {e.block_ids.length > 4 && <span className="kg-rel-dim"> +{e.block_ids.length - 4}</span>}
        </span>
      </div>
      {open && (
        <div className="kg-body">
          {e.description && <p className="kg-desc">{e.description}</p>}
          {mine.length > 0 ? (
            <ul className="kg-rels">
              {mine.map((r) => (
                <RelationLine
                  key={r.id}
                  r={r}
                  self={e.id}
                  blockText={blockText}
                  onPick={onPick}
                  onReject={(id) => void state.rejectRelation(id)}
                />
              ))}
            </ul>
          ) : (
            <p className="search-note">本文里没有和它有关的关系。</p>
          )}
          {mode === "rename" && (
            <form
              className="kg-edit kg-edit-row"
              onSubmit={async (ev) => {
                ev.preventDefault();
                if (name.trim() && (await state.rename(e.id, name.trim()))) setMode(null);
              }}
            >
              <input
                className="inp"
                aria-label="新名称"
                autoFocus
                value={name}
                onChange={(ev) => setName(ev.target.value)}
                onKeyDown={(ev) => ev.key === "Escape" && setMode(null)}
              />
              <Button small variant="primary" type="submit" disabled={!name.trim()}>
                保存
              </Button>
              <Button small variant="ghost" onClick={() => setMode(null)}>
                取消
              </Button>
            </form>
          )}
          {mode === "merge" && <MergePicker entity={e} state={state} onDone={() => setMode(null)} />}
          {mode === "split" && <SplitPicker entity={e} state={state} onDone={() => setMode(null)} />}
          {mode === null && (
            <div className="kg-actions">
              <Button
                small
                variant="ghost"
                icon="edit"
                onClick={() => {
                  setName(e.name);
                  setMode("rename");
                }}
              >
                改名
              </Button>
              <Button small variant="ghost" onClick={() => setMode("merge")}>
                合并到…
              </Button>
              {e.aliases.length > 0 && (
                <Button small variant="ghost" onClick={() => setMode("split")}>
                  拆分
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function entityLabel(e: KgEntity): string {
  const alias = e.aliases.length ? `（${e.aliases.join("、")}）` : "";
  return `${e.name}${alias}${e.description ? ` — ${e.description}` : ""}`;
}

/** 一条合并建议："本篇写法 ⇄ 已有实体"，合并 = 把前者并入后者；不是 = 以后不再建议。 */
function SuggestionLine({ x, state }: { x: KgSuggestion; state: Props["state"] }) {
  const [busy, setBusy] = useState(false);
  const act = async (fn: (id: string) => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn(x.id);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="kg-rel">
      <span className="kg-rel-text">
        <span className="kg-rel-dim">[{typeLabel(x.entity.type)}]</span>{" "}
        <span title={entityLabel(x.entity)}>{x.entity.name}</span> <span className="kg-rel-type">⇄</span>{" "}
        <span title={entityLabel(x.candidate)}>{x.candidate.name}</span>
        {x.candidate.doc_count > 0 && <span className="kg-rel-dim"> · {x.candidate.doc_count} 篇</span>}
      </span>
      <span className="kg-sugg-actions">
        <Button small disabled={busy} onClick={() => void act(state.acceptSuggestion)}>
          合并
        </Button>
        <Button small variant="ghost" disabled={busy} onClick={() => void act(state.dismissSuggestion)}>
          不是
        </Button>
      </span>
    </li>
  );
}

export function KgPanel({ state, blockText, onPick, onClose }: Props) {
  const { graph, job, extracting, extract } = state;
  const [filter, setFilter] = useState<Filter>("all");
  const entities = graph?.entities ?? [];
  const relations = graph?.relations ?? [];
  const results = relations.filter((r) => r.type === "achieves");
  const suggestions = (graph?.suggestions ?? []).filter((x) => filter === "all" || x.entity.type === filter);

  const groups = useMemo(
    () =>
      ENTITY_TYPES.filter((t) => filter === "all" || t.value === filter)
        .map((t) => ({ ...t, items: entities.filter((e) => e.type === t.value) }))
        .filter((g) => g.items.length),
    [entities, filter],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of entities) c[e.type] = (c[e.type] ?? 0) + 1;
    return c;
  }, [entities]);

  return (
    <aside className="side-panel kg-panel" aria-label="知识图谱">
      <div className="side-panel-head">
        <h2 className="serif">图谱</h2>
        <IconButton icon="close" label="关闭图谱" onClick={onClose} />
      </div>
      <div className="summary-controls">
        <Select
          label="实体类型"
          hideLabel
          value={filter}
          options={[
            { value: "all", label: `全部类型（${entities.length}）` },
            ...ENTITY_TYPES.map((t) => ({
              value: t.value,
              label: `${t.label}（${counts[t.value] ?? 0}）`,
              disabled: !counts[t.value],
            })),
          ]}
          onValue={setFilter}
        />
        <Button small icon="sync" disabled={extracting} onClick={() => void extract()}>
          {graph?.kg_status === "ready" ? "重新抽取" : "抽取图谱"}
        </Button>
      </div>
      {extracting && (
        <div className="summary-progress">
          <Progress value={job?.status === "running" && job.progress ? job.progress : undefined} />
          <span>{job?.status === "queued" ? "等待抽取…" : (job?.message ?? "正在抽取实体和关系…")}</span>
        </div>
      )}
      {job?.status === "failed" && !extracting && <p className="search-note error">抽取失败：{job.error}</p>}
      {job?.status === "done" && !extracting && job.message && <p className="search-note">{job.message}</p>}
      <div className="gl-body">
        {graph && !entities.length && !extracting && (
          <p className="search-note">
            还没有图谱。抽取会按章节把论文发给模型，找出方法、模型、数据集、指标等实体和它们的关系，每条关系都标出原文出处。
          </p>
        )}
        {suggestions.length > 0 && (
          <>
            <h3 title="名称不同、但模型判断可能是同一个的实体。只有名称或别名完全相同才会自动合并。">
              可能重复（{suggestions.length}）
            </h3>
            <ul className="kg-rels kg-sugg">
              {suggestions.map((x) => (
                <SuggestionLine key={x.id} x={x} state={state} />
              ))}
            </ul>
          </>
        )}
        {results.length > 0 && (filter === "all" || filter === "Metric") && (
          <>
            <h3>数值结果（{results.length}）</h3>
            <ul className="kg-rels">
              {results.map((r) => (
                <RelationLine
                  key={r.id}
                  r={r}
                  blockText={blockText}
                  onPick={onPick}
                  onReject={(id) => void state.rejectRelation(id)}
                />
              ))}
            </ul>
          </>
        )}
        {groups.map((g) => (
          <section key={g.value}>
            <h3>
              {g.label}（{g.items.length}）
            </h3>
            <ul className="gl-list">
              {g.items.map((e) => (
                <EntityItem
                  key={e.id}
                  e={e}
                  relations={relations}
                  state={state}
                  blockText={blockText}
                  onPick={onPick}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
      {entities.length > 0 && (
        <div className="panel-foot">
          实体在全库共享：名称或别名完全相同的自动合并，其余在"可能重复"里确认；改名、合并、拆分对所有文献生效，重新抽取也不会推翻。
        </div>
      )}
    </aside>
  );
}
