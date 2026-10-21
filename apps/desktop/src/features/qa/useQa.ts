// 单篇问答（docs/m2/qa.md、docs/m3/qa-tree.md）：打开面板时拉对话列表（只读本地库，离线可读），
// 提问时第一次自动建对话；答案经 SSE 流式返回，最后以校验后的 answer 为准。
// 对话是一棵问答树：active 是正在读的节点（阅读区显示根到它的路径），target 是下一个问题挂在哪。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { streamSse } from "../../api/sse";
import { useApp } from "../../app/store";
import { buildTree, latestLeaf, parentOf } from "./tree";

export type QaNode = Schemas["QANodeOut"];
export type QaSession = Schemas["QASessionOut"];

/** 下一个问题的位置：parentId 为 null 是新话题（新的根）。 */
export interface QaTarget {
  parentId: string | null;
  /** 就此追问：父节点回答里选中的文字 */
  anchor?: string;
  /** 另起：与这个节点同级（只用于界面上的说明） */
  besideId?: string;
}

export interface PendingTurn {
  question: string;
  parentId: string | null;
  anchor?: string;
  text: string; // 流式原文（引用未校验，只用于即时显示）
  modes: string[] | null;
}

interface AskOptions extends QaTarget {
  regenerate?: boolean;
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
  const [active, setActive] = useState<string | null>(null);
  const [target, setTarget] = useState<QaTarget>({ parentId: null });
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [consent, setConsent] = useState<{ providerId: string; message: string } | null>(null);
  const [lastModes, setLastModes] = useState<string[] | null>(null);
  const abort = useRef<AbortController | null>(null);
  const lastAsk = useRef<{ question: string; opts: AskOptions } | null>(null);
  const toast = useApp((s) => s.toast);
  const tree = useMemo(() => buildTree(nodes), [nodes]);

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
      setActive(null);
      setTarget({ parentId: null });
      return;
    }
    const detail = unwrap(await api().GET("/qa/sessions/{session_id}", { params: { path: { session_id: sessionId } } }));
    setNodes(detail.nodes);
    // 接着读最近的一轮
    const last = detail.nodes[detail.nodes.length - 1]?.id ?? null;
    setActive(last);
    setTarget({ parentId: last });
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
    async (question: string, opts: AskOptions = target) => {
      question = question.trim();
      if (!question) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      lastAsk.current = { question, opts };
      setError(null);
      setPending({ question, parentId: opts.parentId, anchor: opts.anchor, text: "", modes: null });
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
            body: JSON.stringify({
              question,
              lang,
              parent_id: opts.parentId,
              anchor: opts.anchor ?? null,
              regenerate: Boolean(opts.regenerate),
            }),
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
              const node = e.data as QaNode;
              setNodes((list) => [...list, node]);
              setActive(node.id);
              setTarget({ parentId: node.id });
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
    [current, docId, lang, refreshSessions, target, toast],
  );

  /** 读这个节点（阅读区显示根到它的路径），之后的问题追问它。 */
  const focus = useCallback((id: string) => {
    setActive(id);
    setTarget({ parentId: id });
    setError(null);
  }, []);

  /** 切到另一支：读那一支最近的内容。 */
  const switchTo = useCallback((id: string) => focus(latestLeaf(tree, id)), [focus, tree]);

  /** 另起：与 id 同级提新问题（id 是根时就是新话题）。 */
  const diverge = useCallback(
    (id: string) => {
      setActive(id);
      setTarget({ parentId: parentOf(tree, id), besideId: id });
    },
    [tree],
  );

  /** 重答：同一父节点下把同一个问题再问一次（不用缓存），结果作为兄弟节点。 */
  const retake = useCallback(
    (id: string) => {
      const node = tree.byId.get(id);
      if (!node) return;
      void ask(node.question, { parentId: parentOf(tree, id), anchor: node.anchor?.text as string | undefined, regenerate: true });
    },
    [ask, tree],
  );

  /** 就此追问：在 id 的回答里选中了 text。 */
  const spawnFromSelection = useCallback((id: string, text: string) => {
    setActive(id);
    setTarget({ parentId: id, anchor: text });
  }, []);

  const newTopic = useCallback(() => setTarget({ parentId: null }), []);

  /** 删除节点及其子树。 */
  const removeNode = useCallback(
    async (id: string) => {
      const parent = parentOf(tree, id);
      const r = await api().DELETE("/qa/nodes/{node_id}", { params: { path: { node_id: id } } });
      if (!r.response.ok && r.response.status !== 404) {
        toast(`删除失败：HTTP ${r.response.status}`);
        return;
      }
      if (!current) return;
      const detail = unwrap(await api().GET("/qa/sessions/{session_id}", { params: { path: { session_id: current } } }));
      setNodes(detail.nodes);
      const still = (x: string | null) => x !== null && detail.nodes.some((n) => n.id === x);
      if (!still(active)) {
        setActive(parent);
        setTarget({ parentId: parent });
      } else if (!still(target.parentId)) {
        setTarget({ parentId: active });
      }
      void refreshSessions().catch(() => undefined);
    },
    [active, current, refreshSessions, target.parentId, toast, tree],
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
    if (lastAsk.current) void ask(lastAsk.current.question, lastAsk.current.opts);
  }, [consent, ask]);

  const declineConsent = useCallback(() => setConsent(null), []);
  const cancel = useCallback(() => abort.current?.abort(), []);

  return {
    sessions,
    current,
    nodes,
    tree,
    active,
    target,
    pending,
    running: pending !== null,
    error,
    lastModes,
    select,
    ask,
    focus,
    switchTo,
    diverge,
    retake,
    spawnFromSelection,
    newTopic,
    removeNode,
    cancel,
    remove,
    consent,
    acceptConsent,
    declineConsent,
  };
}
