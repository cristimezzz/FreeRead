// 知识图谱（docs/m3/kg.md）：本篇的实体与关系，每条关系带出处块。
// 抽取是后台任务 kg_extract，完成后重新拉取；合并 / 拆分对全库生效。
// 跨文献只有名称 / 别名完全相同才自动合并，其余"可能重复"由用户确认或否决。

import { useCallback, useEffect, useState } from "react";
import { api, preflightError, unwrap, type Schemas } from "../../api/client";
import { useApp } from "../../app/store";

export type KgGraph = Schemas["DocGraphOut"];
export type KgEntity = Schemas["EntityOut"];
export type KgRelation = Schemas["RelationOut"];
export type KgSuggestion = Schemas["SuggestionOut"];
export type KgEntityType = NonNullable<Schemas["EntityPatch"]["type"]>;

export const ENTITY_TYPES: { value: KgEntityType; label: string }[] = [
  { value: "Method", label: "方法" },
  { value: "Model", label: "模型" },
  { value: "Dataset", label: "数据集" },
  { value: "Metric", label: "指标" },
  { value: "Task", label: "任务" },
  { value: "Concept", label: "概念" },
  { value: "Claim", label: "论断" },
];

export const RELATION_LABEL: Record<string, string> = {
  proposes: "提出，用于",
  uses: "使用",
  improves_on: "改进",
  evaluated_on: "评估于",
  achieves: "取得",
  compares_with: "对比",
  contradicts: "矛盾于",
  part_of: "属于",
};

export function typeLabel(t: string): string {
  return ENTITY_TYPES.find((e) => e.value === t)?.label ?? t;
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

  const run = useCallback(
    async <T>(fn: () => Promise<T>, what: string): Promise<T | null> => {
      try {
        const out = await fn();
        await refresh();
        return out;
      } catch (e) {
        toast(`${what}失败：${e instanceof Error ? e.message : e}`);
        return null;
      }
    },
    [refresh, toast],
  );

  const extract = useCallback(async () => {
    try {
      unwrap(await api().POST("/documents/{doc_id}/kg/extract", { params: { path: { doc_id: docId } } }));
    } catch (e) {
      const p = preflightError(e);
      if (p?.code === "consent_required" && p.provider_id) setConsent({ providerId: p.provider_id, message: p.message });
      else toast(`无法抽取图谱：${p?.message ?? e}${p ? "。请到设置里配置大模型服务。" : ""}`);
    }
  }, [docId, toast]);

  const rename = useCallback(
    (id: string, name: string) =>
      run(
        async () =>
          unwrap(await api().PATCH("/kg/entities/{entity_id}", { params: { path: { entity_id: id } }, body: { name } })),
        "改名",
      ),
    [run],
  );

  /** 把 sourceId 并入 targetId。 */
  const merge = useCallback(
    (targetId: string, sourceId: string) =>
      run(
        async () =>
          unwrap(
            await api().POST("/kg/entities/{entity_id}/merge", {
              params: { path: { entity_id: targetId } },
              body: { source_ids: [sourceId] },
            }),
          ),
        "合并",
      ),
    [run],
  );

  const split = useCallback(
    (id: string, aliases: string[]) =>
      run(
        async () =>
          unwrap(
            await api().POST("/kg/entities/{entity_id}/split", { params: { path: { entity_id: id } }, body: { aliases } }),
          ),
        "拆分",
      ),
    [run],
  );

  const rejectRelation = useCallback(
    (id: string) =>
      run(async () => {
        const r = await api().DELETE("/kg/relations/{relation_id}", { params: { path: { relation_id: id } } });
        if (!r.response.ok) throw new Error(`HTTP ${r.response.status}`);
      }, "删除关系"),
    [run],
  );

  const acceptSuggestion = useCallback(
    (id: string) =>
      run(
        async () =>
          unwrap(
            await api().POST("/kg/suggestions/{suggestion_id}/accept", { params: { path: { suggestion_id: id } } }),
          ),
        "合并",
      ),
    [run],
  );

  const dismissSuggestion = useCallback(
    (id: string) =>
      run(async () => {
        const r = await api().POST("/kg/suggestions/{suggestion_id}/dismiss", {
          params: { path: { suggestion_id: id } },
        });
        if (!r.response.ok) throw new Error(`HTTP ${r.response.status}`);
      }, "忽略建议"),
    [run],
  );

  const search = useCallback(
    async (q: string, type: KgEntityType): Promise<KgEntity[]> => {
      try {
        return unwrap(await api().GET("/kg/entities", { params: { query: { q, type, limit: 12 } } }));
      } catch (e) {
        toast(`搜索实体失败：${e}`);
        return [];
      }
    },
    [toast],
  );

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

  return {
    graph,
    job,
    extracting,
    extract,
    rename,
    merge,
    split,
    rejectRelation,
    acceptSuggestion,
    dismissSuggestion,
    search,
    consent,
    acceptConsent,
    declineConsent,
  };
}
