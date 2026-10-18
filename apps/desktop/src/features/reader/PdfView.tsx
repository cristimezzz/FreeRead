// 原版 PDF 视图（pdf.js）。页面按需渲染；点击换算成 PDF 点坐标交给定位逻辑；
// 定位高亮用 tertiary 色（ADR-0006）。

import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { coreInfo } from "../../api/client";
import type { Anchor } from "../../api/ir";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const PAGE_GAP = 16;
const PADDING = 16;

interface Props {
  docId: string;
  highlight: Anchor | null;
  /** 每次值变化时滚动到 highlight（定位来自重排视图时） */
  scrollKey: number;
  onPoint: (page: number, x: number, y: number) => void;
  onError: (message: string) => void;
}

interface PageSize {
  width: number;
  height: number;
}

export function PdfView({ docId, highlight, scrollKey, onPoint, onError }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [sizes, setSizes] = useState<PageSize[]>([]);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const { baseUrl, token } = coreInfo();
    const task = pdfjs.getDocument({
      url: `${baseUrl}/documents/${docId}/pdf`,
      httpHeaders: { "X-FreeRead-Token": token },
    });
    let cancelled = false;
    task.promise.then(
      async (doc) => {
        const list: PageSize[] = [];
        for (let i = 1; i <= doc.numPages; i++) {
          const vp = (await doc.getPage(i)).getViewport({ scale: 1 });
          list.push({ width: vp.width, height: vp.height });
        }
        if (cancelled) return;
        setSizes(list);
        setPdf(doc);
      },
      (err) => !cancelled && onError(`无法打开 PDF：${err}`),
    );
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [docId, onError]);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const maxPageWidth = Math.max(1, ...sizes.map((s) => s.width));
  const scale = width ? Math.min(2.5, (width - PADDING * 2) / maxPageWidth) : 1;

  useEffect(() => {
    if (!highlight || !container.current) return;
    const page = container.current.querySelector<HTMLElement>(`[data-page="${highlight.page}"]`);
    if (!page) return;
    const top = page.offsetTop + highlight.bbox[1] * scale - container.current.clientHeight / 3;
    container.current.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    // 只在 scrollKey 变化时滚动；PDF 内点击产生的高亮不滚动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollKey]);

  return (
    <div className="reader-pane pdf-view" ref={container}>
      {pdf &&
        sizes.map((s, i) => (
          <PdfPage
            key={i}
            pdf={pdf}
            index={i}
            size={s}
            scale={scale}
            highlight={highlight?.page === i ? highlight.bbox : null}
            onPoint={onPoint}
          />
        ))}
    </div>
  );
}

interface PageProps {
  pdf: pdfjs.PDFDocumentProxy;
  index: number;
  size: PageSize;
  scale: number;
  highlight: Anchor["bbox"] | null;
  onPoint: (page: number, x: number, y: number) => void;
}

function PdfPage({ pdf, index, size, scale, highlight, onPoint }: PageProps) {
  const wrapper = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrapper.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { rootMargin: "800px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !canvas.current) return;
    let task: pdfjs.RenderTask | null = null;
    let cancelled = false;
    void pdf.getPage(index + 1).then((page) => {
      if (cancelled || !canvas.current) return;
      const dpr = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * dpr });
      canvas.current.width = Math.floor(viewport.width);
      canvas.current.height = Math.floor(viewport.height);
      task = page.render({ canvas: canvas.current, viewport });
      task.promise.catch(() => undefined); // 取消渲染会 reject
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [visible, pdf, index, scale]);

  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    onPoint(index, (e.clientX - rect.left) / scale, (e.clientY - rect.top) / scale);
  };

  return (
    <div
      ref={wrapper}
      className="pdf-page"
      data-page={index}
      style={{ width: size.width * scale, height: size.height * scale, marginBottom: PAGE_GAP }}
      onClick={click}
    >
      <canvas ref={canvas} aria-label={`第 ${index + 1} 页`} />
      {highlight && (
        <div
          className="pdf-highlight"
          style={{
            left: highlight[0] * scale - 2,
            top: highlight[1] * scale - 2,
            width: (highlight[2] - highlight[0]) * scale + 4,
            height: (highlight[3] - highlight[1]) * scale + 4,
          }}
        />
      )}
    </div>
  );
}
