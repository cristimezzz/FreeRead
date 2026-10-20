// 高亮与批注（docs/m2/annotations.md）：打开文档时拉列表，增删改后整体刷新。

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, unwrap, type Schemas } from "../../api/client";
import { useApp } from "../../app/store";
import type { Mark } from "./offsets";

export type Annotation = Schemas["AnnotationOut"];
export type AnnotationColor = Annotation["color"];

export const COLORS: { value: AnnotationColor; label: string }[] = [
  { value: "yellow", label: "黄" },
  { value: "green", label: "绿" },
  { value: "blue", label: "蓝" },
  { value: "pink", label: "粉" },
  { value: "purple", label: "紫" },
];

/** irVersion：重新解析后块 ID 和区间可能都变了，要重新拉。 */
export function useAnnotations(docId: string, irVersion: number) {
  const [items, setItems] = useState<Annotation[]>([]);
  const toast = useApp((s) => s.toast);

  const refresh = useCallback(async () => {
    setItems(unwrap(await api().GET("/documents/{doc_id}/annotations", { params: { path: { doc_id: docId } } })));
  }, [docId]);

  useEffect(() => {
    void refresh().catch(() => undefined);
  }, [refresh, irVersion]);

  const create = useCallback(
    async (blockId: string, start: number | null, end: number | null, color: AnnotationColor, note = "") => {
      try {
        const a = unwrap(
          await api().POST("/documents/{doc_id}/annotations", {
            params: { path: { doc_id: docId } },
            body: { block_id: blockId, start, end, color, note },
          }),
        );
        await refresh();
        return a;
      } catch (e) {
        toast(`添加批注失败：${e instanceof Error ? e.message : e}`);
        return null;
      }
    },
    [docId, refresh, toast],
  );

  const update = useCallback(
    async (id: string, patch: { color?: AnnotationColor; note?: string }) => {
      try {
        const a = unwrap(
          await api().PATCH("/annotations/{annotation_id}", { params: { path: { annotation_id: id } }, body: patch }),
        );
        setItems((list) => list.map((x) => (x.id === id ? a : x)));
      } catch (e) {
        toast(`保存批注失败：${e instanceof Error ? e.message : e}`);
      }
    },
    [toast],
  );

  const remove = useCallback(
    async (id: string) => {
      const r = await api().DELETE("/annotations/{annotation_id}", { params: { path: { annotation_id: id } } });
      if (!r.response.ok && r.response.status !== 404) toast(`删除批注失败：HTTP ${r.response.status}`);
      setItems((list) => list.filter((x) => x.id !== id));
    },
    [toast],
  );

  // 每个块的区间批注（渲染 <mark>）与整块批注；stale 的不画
  const { marks, wholeBlocks } = useMemo(() => {
    const marks: Record<string, Mark[]> = {};
    const wholeBlocks: Record<string, Annotation> = {};
    for (const a of items) {
      if (a.status !== "ok") continue;
      if (a.start == null || a.end == null) wholeBlocks[a.block_id] = a;
      else
        (marks[a.block_id] ??= []).push({
          id: a.id,
          start: a.start,
          end: a.end,
          color: a.color,
          hasNote: Boolean(a.note.trim()),
        });
    }
    return { marks, wholeBlocks };
  }, [items]);

  return { items, marks, wholeBlocks, create, update, remove, refresh };
}
