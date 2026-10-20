// <img> 不能带 X-FreeRead-Token 头：用 fetch 取图片再转成 blob URL。
// 重新解析后图片原地替换（同名 a_0000.png）：version 取 IR 的生成时间，变了就重新取，
// 并且不用 HTTP 缓存里的旧图。

import { useEffect, useState } from "react";
import { rawFetch } from "../../api/client";

export function useAssetUrl(docId: string, path: string | undefined, version?: string): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    const name = path.split("/").pop();
    let objectUrl: string | null = null;
    let cancelled = false;
    rawFetch(`/documents/${docId}/assets/${name}`, { cache: "no-cache" })
      .then((r) => r.blob())
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId, path, version]);
  return url;
}
