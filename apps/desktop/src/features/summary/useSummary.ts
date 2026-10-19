// 分层总结（docs/01-architecture.md §5.6）：打开面板时拉已有总结（只读本地库），
// 用户点"生成"后经 SSE 拿进度和结果。

import { useCallback, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { streamSse } from "../../api/sse";
import { useApp } from "../../app/store";

export type Summary = Schemas["SummaryOut"];
export type Template = Schemas["TemplateOut"];
// SSE 事件体不在 OpenAPI 里（core/freeread/services/summary.py SummaryProgress）
interface Progress {
  stage: "map" | "reduce";
  done: number;
  total: number;
  title?: string | null;
}

interface SummaryError {
  code: string;
  message: string;
  provider_id?: string | null;
}

export function useSummary(docId: string, lang: string, enabled: boolean) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [summaries, setSummaries] = useState<Summary[]>([]);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consent, setConsent] = useState<{ providerId: string; message: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const lastTemplate = useRef<string | null>(null);
  const toast = useApp((s) => s.toast);

  const refresh = useCallback(async () => {
    const list = unwrap(
      await api().GET("/documents/{doc_id}/summaries", { params: { path: { doc_id: docId }, query: { lang } } }),
    );
    setSummaries(list);
  }, [docId, lang]);

  useEffect(() => {
    if (!enabled) return;
    void api()
      .GET("/summary/templates")
      .then((r) => setTemplates(unwrap(r)))
      .catch(() => undefined);
    void refresh().catch(() => undefined);
  }, [enabled, refresh]);

  // 关闭面板 / 切换文档时中止进行中的生成（服务端会取消未完成的调用，已完成的进了缓存）
  useEffect(() => () => abort.current?.abort(), [docId, enabled]);

  const generate = useCallback(
    async (templateId: string) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      lastTemplate.current = templateId;
      setRunning(true);
      setError(null);
      setProgress(null);
      try {
        await streamSse(
          `/documents/${docId}/summary`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template_id: templateId, lang }),
            signal: controller.signal,
          },
          (e) => {
            if (e.event === "progress") setProgress(e.data as Progress);
            else if (e.event === "summary") {
              const s = e.data as Summary;
              setSummaries((list) => [s, ...list.filter((x) => x.template_id !== s.template_id)]);
            } else if (e.event === "error") {
              const err = e.data as SummaryError;
              if (err.code === "consent_required" && err.provider_id) {
                setConsent({ providerId: err.provider_id, message: err.message });
              } else if (err.code === "route_not_configured" || err.code === "missing_api_key") {
                setError(`${err.message}。请到 设置 › 大模型服务 中配置。`);
              } else {
                setError(err.message);
              }
            }
          },
        );
      } catch (err) {
        if (!controller.signal.aborted) toast(`总结请求失败：${err}`);
      } finally {
        if (abort.current === controller) {
          abort.current = null;
          setRunning(false);
          setProgress(null);
        }
      }
    },
    [docId, lang, toast],
  );

  /** 用户确认隐私提示后：记下同意并重试。 */
  const acceptConsent = useCallback(async () => {
    const settings = useApp.getState().settings;
    if (!consent || !settings) return;
    await useApp.getState().saveSettings({
      ...settings,
      consented_providers: [...new Set([...settings.consented_providers, consent.providerId])],
    });
    setConsent(null);
    if (lastTemplate.current) void generate(lastTemplate.current);
  }, [consent, generate]);

  const declineConsent = useCallback(() => setConsent(null), []);
  const cancel = useCallback(() => abort.current?.abort(), []);

  return { templates, summaries, progress, running, error, generate, cancel, consent, acceptConsent, declineConsent };
}
