import { useEffect, useRef, useState } from "react";
import { rawFetch } from "../../api/client";
import type { Block } from "../../api/ir";
import type { FigureGroup } from "./figureLayout";
import { useAssetUrl } from "./useAssetUrl";

interface Props {
  group: FigureGroup;
  docId: string;
  version: string;
  assetPaths: ReadonlyMap<string, string>;
  located: string | null;
  wholeMarks?: Record<string, string>;
  onLocate: (block: Block) => void;
}

export function FigureGroupView({ group, docId, version, assetPaths, located, wholeMarks, onLocate }: Props) {
  const ref = useRef<HTMLElement>(null);
  const [crop, setCrop] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const { page } = group;
  const [left, top, right, bottom] = group.bbox;

  useEffect(() => {
    const figure = ref.current;
    if (!figure) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      const query = new URLSearchParams({
        page: String(page), x0: String(left), y0: String(top), x1: String(right), y1: String(bottom),
      });
      void (async () => {
        try {
          const response = await rawFetch(`/documents/${docId}/figure-crop?${query}`, { signal: controller.signal });
          const blob = await response.blob();
          if (controller.signal.aborted) return;
          objectUrl = URL.createObjectURL(blob);
          setCrop(objectUrl);
        } catch {
          if (!controller.signal.aborted) setFailed(true);
        }
      })();
    }, { root: figure.closest(".reader-pane"), rootMargin: "100% 0px" });
    observer.observe(figure);
    return () => {
      observer.disconnect();
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId, version, page, left, top, right, bottom]);

  const width = right - left;
  const height = bottom - top;
  const label = group.caption.label || group.caption.text;
  return (
    <figure ref={ref} className="rf-figure-group" aria-label={label} style={{ aspectRatio: width / height }}>
      {crop && !failed && <img className="rf-figure-crop" src={crop} alt="" onError={() => setFailed(true)} />}
      {[...group.panels, ...group.labels].map(({ block, bbox: [x0, y0, x1, y1] }, i) => (
        <button
          key={block.id}
          type="button"
          className={`rf-block rf-figure-part${located === block.id ? " located" : ""}`}
          data-block-id={block.id}
          data-type={block.type}
          data-mark={wholeMarks?.[block.id]}
          aria-label={block.label || block.text || `${label} · 子图 ${i + 1}`}
          style={{
            left: `${100 * (x0 - left) / width}%`, top: `${100 * (y0 - top) / height}%`,
            width: `${100 * (x1 - x0) / width}%`, height: `${100 * (y1 - y0) / height}%`,
          }}
          onClick={() => onLocate(block)}
        >
          {failed && (block.type === "figure" ? (
            <PanelImage docId={docId} path={block.asset_id ? assetPaths.get(block.asset_id) : undefined} version={version} />
          ) : <span>{block.text}</span>)}
        </button>
      ))}
    </figure>
  );
}

function PanelImage({ docId, path, version }: { docId: string; path?: string; version: string }) {
  const url = useAssetUrl(docId, path, version);
  return url ? <img src={url} alt="" /> : null;
}
