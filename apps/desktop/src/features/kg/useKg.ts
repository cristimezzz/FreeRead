// 知识图谱（docs/m3/kg.md）：每篇论文一张图，只留重要的实体，每条关系带出处块。
// 抽取是后台任务 kg_extract，完成后重新拉取；阅读器里画成 3D 链接云图（KgCloud）。

import { useCallback, useEffect, useState } from "react";
import { api, preflightError, unwrap, type Schemas } from "../../api/client";
import { useApp } from "../../app/store";

export type KgGraph = Schemas["DocGraphOut"];
export type KgEntity = Schemas["EntityOut"];
export type KgRelation = Schemas["RelationOut"];

/** 顺序与 theme.ts 的 KG_COLORS 一致（图例按这个顺序）。 */
export const ENTITY_TYPES = [
  { value: "Method", label: "方法" },
  { value: "Model", label: "模型" },
  { value: "Metric", label: "指标" },
  { value: "Task", label: "任务" },
  { value: "Dataset", label: "数据集" },
  { value: "Concept", label: "概念" },
] as const;
export type KgEntityType = (typeof ENTITY_TYPES)[number]["value"];

export const RELATION_LABEL: Record<string, string> = {
  proposes: "提出，用于",
  uses: "使用",
  improves_on: "改进",
  evaluated_on: "评估于",
  achieves: "取得",
  compares_with: "对比",
  part_of: "属于",
};

export function typeLabel(t: string): string {
  return ENTITY_TYPES.find((e) => e.value === t)?.label ?? t;
}

/** achieves 的数值："top-1 accuracy = 85.3%"。 */
export function formatValue(r: KgRelation): string {
  const a = r.attrs as { metric?: string; value_text?: string; value?: number; unit?: string };
  const v = a.value_text ?? (a.value != null ? String(a.value) : "");
  return `${a.metric ?? r.dst_name} = ${v}${a.unit ? ` ${a.unit}` : ""}`;
}

export interface CloudNode {
  id: string;
  name: string;
  type: string;
  val: number; // 节点体积（3d-force-graph 按 val 的立方根定半径）
}

export interface CloudLink {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  stale: boolean;
}

/** 图谱 → 云图数据。隐藏的类型连同它们的连线一起去掉；同一对实体之间的多条关系各画一条。 */
export function toCloudData(
  graph: Pick<KgGraph, "entities" | "relations"> | null,
  hidden: ReadonlySet<string> = new Set(),
): { nodes: CloudNode[]; links: CloudLink[] } {
  if (!graph) return { nodes: [], links: [] };
  const nodes = graph.entities
    .filter((e) => !hidden.has(e.type))
    .map((e) => ({ id: e.id, name: e.name, type: e.type, val: 1 + e.score }));
  const shown = new Set(nodes.map((n) => n.id));
  const links = graph.relations
    .filter((r) => shown.has(r.src_id) && shown.has(r.dst_id))
    .map((r) => ({
      id: r.id,
      source: r.src_id,
      target: r.dst_id,
      type: r.type,
      label: r.type === "achieves" ? formatValue(r) : (RELATION_LABEL[r.type] ?? r.type),
      stale: r.status === "stale",
    }));
  return { nodes, links };
}

export function useKg(docId: string, enabled: boolean) {
  const [graph, setGraph] = useState<KgGraph | null>(null);
  const [consent, setConsent] = useState<{ providerId: string; message: string } | null>(null);
  const toast = useApp((s) => s.toast);
  const jobs = useApp((s) => s.jobs);

  // 本文档最近的抽取任务
  const job = Object.values(jobs)
    .filter((j) => j.kind === "kg_extract" && j.payload.doc_id === docId)
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const extracting = job?.status === "queued" || job?.status === "running";
  const jobKey = job ? `${job.id}:${job.status}` : "";

  const refresh = useCallback(async () => {
    setGraph(unwrap(await api().GET("/documents/{doc_id}/kg", { params: { path: { doc_id: docId } } })));
  }, [docId]);

  useEffect(() => {
    if (!enabled) return;
    void refresh().catch((e) => toast(`加载图谱失败：${e}`));
  }, [enabled, refresh, jobKey, toast]);

  const extract = useCallback(async () => {
    try {
      unwrap(await api().POST("/documents/{doc_id}/kg/extract", { params: { path: { doc_id: docId } } }));
    } catch (e) {
      const p = preflightError(e);
      if (p?.code === "consent_required" && p.provider_id) setConsent({ providerId: p.provider_id, message: p.message });
      else toast(`无法抽取图谱：${p?.message ?? e}${p ? "。请到设置里配置大模型服务。" : ""}`);
    }
  }, [docId, toast]);

  const acceptConsent = useCallback(async () => {
    const settings = useApp.getState().settings;
    if (!consent || !settings) return;
    await useApp.getState().saveSettings({
      ...settings,
      consented_providers: [...new Set([...settings.consented_providers, consent.providerId])],
    });
    setConsent(null);
    void extract();
  }, [consent, extract]);

  const declineConsent = useCallback(() => setConsent(null), []);

  return { graph, job, extracting, extract, consent, acceptConsent, declineConsent };
}
