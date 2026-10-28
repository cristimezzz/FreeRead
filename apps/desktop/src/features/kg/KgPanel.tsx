import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Shimmer } from "../../components/ai-elements/shimmer";
import { Citation } from "../../components/Citation";
import { IconButton, ProgressBar } from "../../components/controls";
import { Icon } from "../../components/icons";
import { PanelNote, SidePanel } from "../../components/SidePanel";
import { Button } from "../../components/ui/button";
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
  /** 展开后云图铺满阅读区：覆盖层元素由 ReaderView 提供 */
  expanded: boolean;
  stage: HTMLElement | null;
  onExpand: (expanded: boolean) => void;
}

type CiteProps = { blockText?: (id: string) => string | undefined; onPick: (id: string) => void };

/** 出处块按阅读顺序编号（b_0000 显示为 1），悬停看原文。 */
function Cite({ id, blockText, onPick }: CiteProps & { id: string }) {
  return <Citation id={id} n={Number(id.replace(/\D/g, "")) + 1} blockText={blockText} onPick={onPick} />;
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

/** 选中关系：两端、数值、原文摘句、出处。同一对实体同类型的多条关系（出自不同的块）一起列出处。 */
function RelationCard({
  rs,
  onSelect,
  ...cite
}: CiteProps & { rs: KgRelation[]; onSelect: (s: Selection) => void }) {
  const r = rs[0];
  const quotes = rs.filter((x) => x.evidence).slice(0, 3);
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
      {quotes.map((x) => (
        <blockquote key={x.id} className="kg-card-quote">
          {x.evidence}
        </blockquote>
      ))}
      <p className="kg-card-cites">
        <span className="kg-card-dim">出处</span>
        {rs.map((x) => (
          <Cite key={x.id} id={x.block_id} {...cite} />
        ))}
        {rs.every((x) => x.status === "stale") && <span className="gl-badge kg-stale">出处已失效</span>}
      </p>
    </>
  );
}

/** 线型图例：与 layout.LINE_STYLE 一致。 */
function LineHint() {
  return (
    <p className="kg-linehint">
      <span>
        <i className="kg-line" data-style="solid" />
        提出 / 改进 / 取得
      </span>
      <span>
        <i className="kg-line" data-style="dashed" />
        使用 / 属于 / 评估于
      </span>
      <span>
        <i className="kg-line" data-style="dotted" />
        对比
      </span>
    </p>
  );
}

export function KgPanel({ state, blockText, onPick: pick, onClose, expanded, stage, onExpand }: Props) {
  const { graph, job, extracting, extract } = state;
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [selected, setSelected] = useState<Selection>(null);
  const entities = graph?.entities ?? [];
  const relations = graph?.relations ?? [];
  const all = useMemo(() => toCloudData(graph), [graph]);
  const data = useMemo(() => toCloudData(graph, hidden), [graph, hidden]);
  // 展开时点出处：先收起，再跳到原文
  const onPick = (id: string) => {
    if (expanded) onExpand(false);
    pick(id);
  };

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onExpand(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded, onExpand]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of entities) c[e.type] = (c[e.type] ?? 0) + 1;
    return c;
  }, [entities]);

  const doneMessage = job?.status === "done" && !extracting ? job.message : "";
  const entity = selected?.kind === "node" ? entities.find((e) => e.id === selected.id) : undefined;
  // 关系按"合并后的线"选中：线的 id 是组里第一条关系
  const select = (s: Selection) =>
    setSelected(
      s?.kind === "link" ? { kind: "link", id: all.links.find((l) => l.ids.includes(s.id))?.id ?? s.id } : s,
    );
  const group = useMemo(() => {
    if (selected?.kind !== "link") return [];
    const ids = all.links.find((l) => l.id === selected.id)?.ids ?? [selected.id];
    return relations.filter((r) => ids.includes(r.id));
  }, [selected, all, relations]);
  const relation = group[0];
  const toggle = (t: string) => {
    const next = new Set(hidden);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setHidden(next);
    if (entity && next.has(entity.type)) setSelected(null);
  };

  return (
    <SidePanel
      title="图谱"
      className="kg-panel"
      aria-label="知识图谱"
      actions={
        <>
          {entities.length > 0 && (
            <IconButton
              icon={expanded ? "collapse" : "expand"}
              label={expanded ? "收起图谱（Esc）" : "展开图谱到阅读区"}
              onClick={() => onExpand(!expanded)}
            />
          )}
          <IconButton icon="close" label="关闭图谱" onClick={onClose} />
        </>
      }
    >
      <div className="flex items-end gap-2 px-6 pb-2">
        <span className="text-muted-foreground flex-1 self-center text-[12.5px]">
          {entities.length > 0 && !doneMessage ? `${entities.length} 个实体 · ${relations.length} 条关系` : ""}
        </span>
        <Button variant="outline" size="sm" disabled={extracting} onClick={() => void extract()}>
          <Icon name="sync" />
          {graph?.kg_status === "ready" ? "重新抽取" : "抽取图谱"}
        </Button>
      </div>
      {extracting && (
        <div className="text-muted-foreground mx-6 mt-2 mb-1 flex flex-col gap-2 text-xs">
          <ProgressBar value={job?.status === "running" && job.progress ? job.progress : undefined} />
          <Shimmer className="text-xs">{job?.status === "queued" ? "等待抽取…" : (job?.message ?? "正在抽取实体和关系…")}</Shimmer>
        </div>
      )}
      {job?.status === "failed" && !extracting && (
        <PanelNote error className="mt-0">
          抽取失败：{job.error}
        </PanelNote>
      )}
      {doneMessage && <PanelNote className="mt-0">{doneMessage}</PanelNote>}
      {graph && !entities.length && !extracting && (
        <PanelNote className="mt-0">
          还没有图谱。抽取会按章节把论文发给模型，找出这篇论文的核心方法、模型、数据集、指标和它们的关系，每条关系都标出原文出处。
        </PanelNote>
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
          <LineHint />
          {expanded && stage ? (
            <>
              <div className="kg-cloud kg-cloud-away">
                <PanelNote className="m-0">图谱已在阅读区展开。</PanelNote>
                <Button variant="outline" size="sm" onClick={() => onExpand(false)}>
                  <Icon name="collapse" />
                  收起
                </Button>
              </div>
              {createPortal(
                <div className="kg-stage-inner">
                  <KgCloud all={all} nodes={data.nodes} links={data.links} selected={selected} onSelect={select} />
                  <Button variant="outline" size="sm" className="kg-stage-close" onClick={() => onExpand(false)}>
                    <Icon name="collapse" />
                    收起（Esc）
                  </Button>
                </div>,
                stage,
              )}
            </>
          ) : (
            <KgCloud all={all} nodes={data.nodes} links={data.links} selected={selected} onSelect={select} />
          )}
          <div className="kg-card" data-empty={!entity && !relation ? "" : undefined} aria-live="polite">
            {entity && (
              <EntityCard e={entity} relations={relations} onSelect={select} blockText={blockText} onPick={onPick} />
            )}
            {relation && <RelationCard rs={group} onSelect={select} blockText={blockText} onPick={onPick} />}
            {!entity && !relation && (
              <p className="kg-card-dim">拖动旋转、滚轮缩放；悬停节点看它的全部关系，点节点看实体和出处，点关系名看原文。</p>
            )}
          </div>
        </>
      )}
    </SidePanel>
  );
}
