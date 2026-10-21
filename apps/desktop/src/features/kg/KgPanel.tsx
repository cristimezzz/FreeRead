import { useMemo, useState } from "react";
import { Button, IconButton, Progress } from "../../components/ui";
import { KgCloud, type Selection } from "./KgCloud";
import {
  ENTITY_TYPES,
  RELATION_LABEL,
  formatValue,
  toCloudData,
  typeLabel,
  type KgEntity,
  type KgRelation,
  type useKg,
} from "./useKg";

interface Props {
  state: ReturnType<typeof useKg>;
  blockText?: (id: string) => string | undefined;
  onPick: (blockId: string) => void;
  onClose: () => void;
}

type CiteProps = { blockText?: (id: string) => string | undefined; onPick: (id: string) => void };

/** 出处块按阅读顺序编号（b_0000 显示为 1），悬停看原文。 */
function Cite({ id, blockText, onPick }: CiteProps & { id: string }) {
  return (
    <button type="button" className="cite" title={blockText?.(id)} onClick={() => onPick(id)}>
      {Number(id.replace(/\D/g, "")) + 1}
    </button>
  );
}

function Swatch({ type }: { type: string }) {
  return <span className="kg-swatch" style={{ background: `var(--kg-${type.toLowerCase()})` }} aria-hidden />;
}

/** 选中实体：类型、描述、别名、出处，以及和它相连的关系（点关系选中那条连线）。 */
function EntityCard({
  e,
  relations,
  onSelect,
  ...cite
}: CiteProps & { e: KgEntity; relations: KgRelation[]; onSelect: (s: Selection) => void }) {
  const mine = relations.filter((r) => r.src_id === e.id || r.dst_id === e.id);
  return (
    <>
      <div className="kg-card-head">
        <Swatch type={e.type} />
        <span className="kg-card-type">{typeLabel(e.type)}</span>
        <strong className="kg-card-name">{e.name}</strong>
      </div>
      {e.aliases.length > 0 && <p className="kg-card-dim">又称：{e.aliases.join("、")}</p>}
      {e.description && <p className="kg-card-desc">{e.description}</p>}
      {e.block_ids.length > 0 && (
        <p className="kg-card-cites">
          <span className="kg-card-dim">出处</span>
          {e.block_ids.slice(0, 12).map((id) => (
            <Cite key={id} id={id} {...cite} />
          ))}
          {e.block_ids.length > 12 && <span className="kg-card-dim"> +{e.block_ids.length - 12}</span>}
        </p>
      )}
      {mine.length > 0 && (
        <ul className="kg-card-rels">
          {mine.map((r) => {
            const out = r.src_id === e.id;
            return (
              <li key={r.id} data-status={r.status}>
                <button type="button" className="kg-rel-link" onClick={() => onSelect({ kind: "link", id: r.id })}>
                  {out ? (
                    <>
                      <span className="kg-rel-type">{RELATION_LABEL[r.type] ?? r.type}</span>{" "}
                      {r.type === "achieves" ? formatValue(r) : r.dst_name}
                    </>
                  ) : (
                    <>
                      {r.src_name} <span className="kg-rel-type">{RELATION_LABEL[r.type] ?? r.type}</span> 它
                    </>
                  )}
                </button>
                <Cite id={r.block_id} {...cite} />
                {r.status === "stale" && <span className="gl-badge kg-stale">出处已失效</span>}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

/** 选中关系：两端、数值、原文摘句、出处。 */
function RelationCard({ r, onSelect, ...cite }: CiteProps & { r: KgRelation; onSelect: (s: Selection) => void }) {
  const a = r.attrs as { dataset?: string; setting?: string };
  return (
    <>
      <div className="kg-card-head kg-card-rel">
        <button type="button" className="kg-rel-link" onClick={() => onSelect({ kind: "node", id: r.src_id })}>
          {r.src_name}
        </button>
        <span className="kg-rel-type">→ {RELATION_LABEL[r.type] ?? r.type} →</span>
        <button type="button" className="kg-rel-link" onClick={() => onSelect({ kind: "node", id: r.dst_id })}>
          {r.dst_name}
        </button>
      </div>
      {r.type === "achieves" && (
        <p className="kg-card-value">
          {formatValue(r)}
          {a.dataset && <span className="kg-card-dim">（{a.dataset}）</span>}
          {a.setting && <span className="kg-card-dim"> · {a.setting}</span>}
        </p>
      )}
      {r.evidence && <blockquote className="kg-card-quote">{r.evidence}</blockquote>}
      <p className="kg-card-cites">
        <span className="kg-card-dim">出处</span>
        <Cite id={r.block_id} {...cite} />
        {r.status === "stale" && <span className="gl-badge kg-stale">出处已失效</span>}
      </p>
    </>
  );
}

export function KgPanel({ state, blockText, onPick, onClose }: Props) {
  const { graph, job, extracting, extract } = state;
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [selected, setSelected] = useState<Selection>(null);
  const entities = graph?.entities ?? [];
  const relations = graph?.relations ?? [];
  const data = useMemo(() => toCloudData(graph, hidden), [graph, hidden]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of entities) c[e.type] = (c[e.type] ?? 0) + 1;
    return c;
  }, [entities]);

  const doneMessage = job?.status === "done" && !extracting ? job.message : "";
  const entity = selected?.kind === "node" ? entities.find((e) => e.id === selected.id) : undefined;
  const relation = selected?.kind === "link" ? relations.find((r) => r.id === selected.id) : undefined;
  const toggle = (t: string) => {
    const next = new Set(hidden);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setHidden(next);
    if (entity && next.has(entity.type)) setSelected(null);
  };

  return (
    <aside className="side-panel kg-panel" aria-label="知识图谱">
      <div className="side-panel-head">
        <h2 className="serif">图谱</h2>
        <IconButton icon="close" label="关闭图谱" onClick={onClose} />
      </div>
      <div className="summary-controls">
        <span className="kg-count">
          {entities.length > 0 && !doneMessage ? `${entities.length} 个实体 · ${relations.length} 条关系` : ""}
        </span>
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
      {job?.status === "failed" && !extracting && <p className="search-note error kg-note">抽取失败：{job.error}</p>}
      {doneMessage && <p className="search-note kg-note">{doneMessage}</p>}
      {graph && !entities.length && !extracting && (
        <p className="search-note kg-note">
          还没有图谱。抽取会按章节把论文发给模型，找出这篇论文的核心方法、模型、数据集、指标和它们的关系，每条关系都标出原文出处。
        </p>
      )}
      {entities.length > 0 && (
        <>
          <div className="kg-legend" role="group" aria-label="按类型显示">
            {ENTITY_TYPES.filter((t) => counts[t.value]).map((t) => (
              <button
                key={t.value}
                type="button"
                className="kg-legend-item"
                aria-pressed={!hidden.has(t.value)}
                onClick={() => toggle(t.value)}
                title={hidden.has(t.value) ? `显示${t.label}` : `隐藏${t.label}`}
              >
                <Swatch type={t.value} />
                {t.label} {counts[t.value]}
              </button>
            ))}
          </div>
          <KgCloud nodes={data.nodes} links={data.links} selected={selected} onSelect={setSelected} />
          <div className="kg-card" data-empty={!entity && !relation ? "" : undefined} aria-live="polite">
            {entity && (
              <EntityCard e={entity} relations={relations} onSelect={setSelected} blockText={blockText} onPick={onPick} />
            )}
            {relation && <RelationCard r={relation} onSelect={setSelected} blockText={blockText} onPick={onPick} />}
            {!entity && !relation && (
              <p className="kg-card-dim">拖动旋转、滚轮缩放；点节点看实体和出处，点连线看关系的原文。</p>
            )}
          </div>
        </>
      )}
    </aside>
  );
}
