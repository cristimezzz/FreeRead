// <img> 不能带 X-FreeRead-Token 头：用 fetch 取图片再转成 blob URL。

import { useEffect, useState } from "react";
import { rawFetch } from "../../api/client";

export function useAssetUrl(docId: string, path: string | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    const name = path.split("/").pop();
    let objectUrl: string | null = null;
    let cancelled = false;
    rawFetch(`/documents/${docId}/assets/${name}`)
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
  }, [docId, path]);
  return url;
}
