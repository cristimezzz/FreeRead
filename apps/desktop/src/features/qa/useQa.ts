// 单篇问答（docs/m2/qa.md）：打开面板时拉对话列表（只读本地库，离线可读），
// 提问时第一次自动建对话；答案经 SSE 流式返回，最后以校验后的 answer 为准。

import { useCallback, useEffect, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { streamSse } from "../../api/sse";
import { useApp } from "../../app/store";

export type QaNode = Schemas["QANodeOut"];
export type QaSession = Schemas["QASessionOut"];

export interface PendingTurn {
  question: string;
  text: string; // 流式原文（引用未校验，只用于即时显示）
  modes: string[] | null;
}

interface QaError {
  code: string;
  message: string;
  provider_id?: string | null;
}

export function useQa(docId: string, lang: string, enabled: boolean) {
  const [sessions, setSessions] = useState<QaSession[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [nodes, setNodes] = useState<QaNode[]>([]);
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [consent, setConsent] = useState<{ providerId: string; message: string } | null>(null);
  const [lastModes, setLastModes] = useState<string[] | null>(null);
  const abort = useRef<AbortController | null>(null);
  const lastQuestion = useRef<string | null>(null);
  const toast = useApp((s) => s.toast);

  const refreshSessions = useCallback(async () => {
    const list = unwrap(await api().GET("/documents/{doc_id}/qa/sessions", { params: { path: { doc_id: docId } } }));
    setSessions(list);
    return list;
  }, [docId]);

  const select = useCallback(async (sessionId: string | null) => {
    abort.current?.abort();
    setCurrent(sessionId);
    setPending(null);
    setError(null);
    if (!sessionId) {
      setNodes([]);
      return;
    }
    const detail = unwrap(await api().GET("/qa/sessions/{session_id}", { params: { path: { session_id: sessionId } } }));
    setNodes(detail.nodes);
  }, []);

  // 打开面板：显示最近的对话
  useEffect(() => {
    if (!enabled) return;
    void refreshSessions()
      .then((list) => (list[0] ? select(list[0].id) : select(null)))
      .catch(() => undefined);
  }, [enabled, refreshSessions, select]);

  // 关闭面板 / 切换文档时中止进行中的提问
  useEffect(() => () => abort.current?.abort(), [docId, enabled]);

  const ask = useCallback(
    async (question: string) => {
      question = question.trim();
      if (!question) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      lastQuestion.current = question;
      setError(null);
      setPending({ question, text: "", modes: null });
      try {
        let sessionId = current;
        if (!sessionId) {
          const created = unwrap(
            await api().POST("/documents/{doc_id}/qa/sessions", { params: { path: { doc_id: docId } }, body: { title: "" } }),
          );
          sessionId = created.id;
          setCurrent(sessionId);
        }
        await streamSse(
          `/qa/sessions/${sessionId}/ask`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, lang }),
            signal: controller.signal,
          },
          (e) => {
            if (e.event === "context") {
              const modes = (e.data as { modes: string[] }).modes;
              setLastModes(modes);
              setPending((p) => (p ? { ...p, modes } : p));
            } else if (e.event === "delta") {
              const text = (e.data as { text: string }).text;
              setPending((p) => (p ? { ...p, text: p.text + text } : p));
            } else if (e.event === "answer") {
              setNodes((list) => [...list, e.data as QaNode]);
              setPending(null);
            } else if (e.event === "error") {
              const err = e.data as QaError;
              setPending(null);
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
        void refreshSessions().catch(() => undefined);
      } catch (err) {
        if (!controller.signal.aborted) toast(`提问失败：${err}`);
      } finally {
        if (abort.current === controller) {
          abort.current = null;
          setPending(null);
        }
      }
    },
    [current, docId, lang, refreshSessions, toast],
  );

  const remove = useCallback(
    async (sessionId: string) => {
      await api().DELETE("/qa/sessions/{session_id}", { params: { path: { session_id: sessionId } } });
      const list = await refreshSessions();
      if (sessionId === current) await select(list[0]?.id ?? null);
    },
    [current, refreshSessions, select],
  );

  /** 用户确认隐私提示后：记下同意并重问。 */
  const acceptConsent = useCallback(async () => {
    const settings = useApp.getState().settings;
    if (!consent || !settings) return;
    await useApp.getState().saveSettings({
      ...settings,
      consented_providers: [...new Set([...settings.consented_providers, consent.providerId])],
    });
    setConsent(null);
    if (lastQuestion.current) void ask(lastQuestion.current);
  }, [consent, ask]);

  const declineConsent = useCallback(() => setConsent(null), []);
  const cancel = useCallback(() => abort.current?.abort(), []);

  return {
    sessions,
    current,
    nodes,
    pending,
    running: pending !== null,
    error,
    lastModes,
    select,
    ask,
    cancel,
    remove,
    consent,
    acceptConsent,
    declineConsent,
  };
}
