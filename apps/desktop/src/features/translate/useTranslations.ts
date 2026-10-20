// 块级翻译（docs/01-architecture.md §5.5）：打开文档时先拉已有译文（离线可读），
// 之后把可视区域内、还没有译文的块合并成一批，经 SSE 逐块拿结果。
// 整篇翻译是后台任务（translate_doc）：任务进度变化时重新拉一次已有译文。

import { useCallback, useEffect, useRef, useState } from "react";
import { api, preflightError, unwrap } from "../../api/client";
import { TRANSLATABLE, type Document } from "../../api/ir";
import { streamSse } from "../../api/sse";
import { useApp } from "../../app/store";

export type TranslationState =
  | { status: "pending" }
  | { status: "ok" | "needs_review"; text: string }
  | { status: "error"; message: string }
  | { status: "skipped" };

interface TranslationEvent {
  block_id: string;
  status: "ok" | "needs_review" | "skipped" | "error";
  text?: string;
  message?: string;
}

interface BatchError {
  code: "route_not_configured" | "missing_api_key" | "consent_required" | string;
  message: string;
  provider_id?: string | null;
}

const DEBOUNCE_MS = 300;
const MAX_BATCH = 30;

/**
 * irVersion：IR 重新加载（如升级为 MinerU 结果）后块 ID 会变，译文要重新拉。
 * reloadKey：整篇翻译任务的进度；变化时把新译文合并进来。
 */
export function useTranslations(
  doc: Document | null,
  enabled: boolean,
  lang: string,
  irVersion = 0,
  reloadKey = "",
) {
  const [states, setStates] = useState<Record<string, TranslationState>>({});
  // retry：确认后要重试的操作（可视区域翻译，或排队整篇翻译）
  const [consent, setConsent] = useState<{ providerId: string; message: string; retry: "visible" | "doc" } | null>(
    null,
  );
  const statesRef = useRef(states);
  statesRef.current = states;
  const wanted = useRef<string[]>([]);
  const lastVisible = useRef<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aborts = useRef(new Set<AbortController>());
  const blocked = useRef(false); // 配置错误时停止自动请求，直到用户处理
  const toast = useApp((s) => s.toast);

  const docId = doc?.doc_id ?? null;

  // 已有译文（只读本地库）
  useEffect(() => {
    setStates({});
    blocked.current = false;
    if (!docId) return;
    let cancelled = false;
    void api()
      .GET("/documents/{doc_id}/translations", { params: { path: { doc_id: docId }, query: { lang } } })
      .then((r) => {
        if (cancelled) return;
        const list = unwrap(r);
        setStates((s) => {
          const next = { ...s };
          for (const t of list) next[t.block_id] = { status: t.status, text: t.text };
          return next;
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [docId, lang, irVersion]);

  // 整篇翻译进行中：合并新译文，不动正在等待 / 出错的块
  useEffect(() => {
    if (!docId || !reloadKey) return;
    let cancelled = false;
    void api()
      .GET("/documents/{doc_id}/translations", { params: { path: { doc_id: docId }, query: { lang } } })
      .then((r) => {
        if (cancelled) return;
        const list = unwrap(r);
        setStates((s) => {
          const next = { ...s };
          for (const t of list) next[t.block_id] = { status: t.status, text: t.text };
          return next;
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [docId, lang, reloadKey]);

  useEffect(() => {
    const current = aborts.current;
    return () => {
      current.forEach((a) => a.abort());
      current.clear();
    };
  }, [docId, lang, irVersion]);

  const translatable = useCallback(
    (id: string) => {
      const b = doc?.blocks.find((x) => x.id === id);
      return Boolean(b && TRANSLATABLE.has(b.type) && b.text.trim());
    },
    [doc],
  );

  const flush = useCallback(async () => {
    if (!docId || blocked.current) return;
    const ids = wanted.current.filter((id) => !statesRef.current[id] && translatable(id)).slice(0, MAX_BATCH);
    wanted.current = [];
    if (!ids.length) return;
    setStates((s) => ({ ...s, ...Object.fromEntries(ids.map((id) => [id, { status: "pending" }])) }));

    const controller = new AbortController();
    aborts.current.add(controller);
    const settled = new Set<string>();
    try {
      await streamSse(
        "/translate/blocks",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ doc_id: docId, block_ids: ids, lang }),
          signal: controller.signal,
        },
        (e) => {
          if (e.event === "translation") {
            const t = e.data as TranslationEvent;
            settled.add(t.block_id);
            setStates((s) => ({
              ...s,
              [t.block_id]:
                t.status === "error"
                  ? { status: "error", message: t.message ?? "" }
                  : t.status === "skipped"
                    ? { status: "skipped" }
                    : { status: t.status, text: t.text ?? "" },
            }));
          } else if (e.event === "error") {
            const err = e.data as BatchError;
            blocked.current = true;
            if (err.code === "consent_required" && err.provider_id) {
              setConsent({ providerId: err.provider_id, message: err.message, retry: "visible" });
            } else {
              toast(`无法翻译：${err.message}。请到设置里配置大模型服务。`);
            }
          }
        },
      );
    } catch (err) {
      if (!controller.signal.aborted) toast(`翻译请求失败：${err}`);
    } finally {
      aborts.current.delete(controller);
      // 没拿到结果的块（被中止、出错）清掉 pending，之后滚回来会再请求
      setStates((s) => {
        const next = { ...s };
        for (const id of ids) if (!settled.has(id) && next[id]?.status === "pending") delete next[id];
        return next;
      });
    }
  }, [docId, lang, toast, translatable]);

  /** ReflowView 上报当前可视区域（含预取范围）内的块，按阅读顺序。 */
  const requestVisible = useCallback(
    (ids: string[]) => {
      lastVisible.current = ids;
      if (!enabled) return;
      wanted.current = ids;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [enabled, flush],
  );

  /** 排队整篇翻译（后台任务，进度在任务栏）。 */
  const translateAll = useCallback(async () => {
    if (!docId) return;
    try {
      unwrap(
        await api().POST("/documents/{doc_id}/translate", { params: { path: { doc_id: docId } }, body: { lang } }),
      );
      toast("已开始翻译全文，进度见底部任务栏");
    } catch (e) {
      const p = preflightError(e);
      if (p?.code === "consent_required" && p.provider_id) {
        setConsent({ providerId: p.provider_id, message: p.message, retry: "doc" });
      } else {
        toast(`无法翻译全文：${p?.message ?? e}${p ? "。请到设置里配置大模型服务。" : ""}`);
      }
    }
  }, [docId, lang, toast]);

  /** 用户确认隐私提示后：记下同意，解除阻塞并重试。 */
  const acceptConsent = useCallback(async () => {
    const settings = useApp.getState().settings;
    if (!consent || !settings) return;
    await useApp.getState().saveSettings({
      ...settings,
      consented_providers: [...new Set([...settings.consented_providers, consent.providerId])],
    });
    setConsent(null);
    blocked.current = false;
    if (consent.retry === "doc") {
      void translateAll();
      return;
    }
    wanted.current = lastVisible.current;
    void flush();
  }, [consent, flush, translateAll]);

  // 打开翻译、或切换文档 / 语言后，补上当前可视区域
  useEffect(() => {
    if (enabled && lastVisible.current.length) requestVisible(lastVisible.current);
  }, [enabled, requestVisible]);

  const declineConsent = useCallback(() => setConsent(null), []);

  return { states, requestVisible, translateAll, consent, acceptConsent, declineConsent };
}
