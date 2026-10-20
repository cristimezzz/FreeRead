// 术语表（docs/m2/glossary.md）：本文档条目 + 全局条目，翻译时注入块里出现的术语。
// 自动抽取是后台任务 glossary_extract，完成后重新拉列表。

import { useCallback, useEffect, useState } from "react";
import { api, preflightError, unwrap, type Schemas } from "../../api/client";
import { useApp } from "../../app/store";

export type Term = Schemas["TermOut"];
export type TermPatch = Schemas["TermPatch"];

/** docId 省略时只管理全局条目（设置页）。 */
export function useGlossary(docId: string | null, lang: string, enabled: boolean) {
  const [terms, setTerms] = useState<Term[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [consent, setConsent] = useState<{ providerId: string; message: string } | null>(null);
  const toast = useApp((s) => s.toast);
  const jobs = useApp((s) => s.jobs);

  // 本文档最近的抽取任务
  const job = docId
    ? Object.values(jobs)
        .filter((j) => j.kind === "glossary_extract" && j.payload.doc_id === docId && j.payload.lang === lang)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0]
    : undefined;
  const extracting = job?.status === "queued" || job?.status === "running";
  const jobKey = job ? `${job.id}:${job.status}` : "";

  const refresh = useCallback(async () => {
    const list = unwrap(
      await api().GET("/glossary", { params: { query: { lang, ...(docId ? { doc_id: docId } : {}) } } }),
    );
    setTerms(list);
    setLoaded(true);
  }, [docId, lang]);

  useEffect(() => {
    if (!enabled) return;
    void refresh().catch((e) => toast(`加载术语表失败：${e}`));
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

  const add = useCallback(
    (source: string, target: string, note = "", global = false) =>
      run(
        async () =>
          unwrap(
            await api().POST("/glossary", {
              body: { source, target, note, lang, doc_id: global || !docId ? null : docId },
            }),
          ),
        "添加术语",
      ),
    [docId, lang, run],
  );

  const update = useCallback(
    (id: string, patch: TermPatch) =>
      run(
        async () => unwrap(await api().PATCH("/glossary/{term_id}", { params: { path: { term_id: id } }, body: patch })),
        "修改术语",
      ),
    [run],
  );

  const remove = useCallback(
    (id: string) =>
      run(async () => {
        const r = await api().DELETE("/glossary/{term_id}", { params: { path: { term_id: id } } });
        if (!r.response.ok) throw new Error(`HTTP ${r.response.status}`);
      }, "删除术语"),
    [run],
  );

  const extract = useCallback(async () => {
    if (!docId) return;
    try {
      unwrap(
        await api().POST("/documents/{doc_id}/glossary/extract", { params: { path: { doc_id: docId } }, body: { lang } }),
      );
    } catch (e) {
      const p = preflightError(e);
      if (p?.code === "consent_required" && p.provider_id) setConsent({ providerId: p.provider_id, message: p.message });
      else toast(`无法抽取术语：${p?.message ?? e}${p ? "。请到设置里配置大模型服务。" : ""}`);
    }
  }, [docId, lang, toast]);

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
    terms,
    loaded,
    job,
    extracting,
    add,
    update,
    remove,
    extract,
    consent,
    acceptConsent,
    declineConsent,
  };
}
