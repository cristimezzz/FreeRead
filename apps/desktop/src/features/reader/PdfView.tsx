// 原版 PDF 视图（pdf.js）。页面按需渲染；点击换算成 PDF 点坐标交给定位逻辑；
// 定位高亮用强调色（ADR-0007）。
// 宽度变化（拖动分隔条、开关侧边面板）分两层：页面框的尺寸走 CSS 变量 --pdf-scale，每一帧直接跟上，
// 期间由 GPU 缩放已有位图；pdf.js 在主线程画一页要几十毫秒，所以重新渲染等宽度停下来再做，
// 而且先画到离屏 canvas，画完再换上，不出现白页。

import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { coreInfo } from "../../api/client";
import { pulse } from "../../components/motion";
import type { Anchor } from "../../api/ir";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const PAGE_GAP = 20;
const PADDING = 28; // 与 styles/reader.css 里 .pdf-view 的 padding 一致
const RESIZE_DEBOUNCE = 150;

function fitScale(width: number, maxPageWidth: number) {
  return Math.min(2.5, (width - PADDING * 2) / maxPageWidth);
}

/** 有批注的块：原版没有文字层，按块的位置在左边距画一条色条 */
export interface PdfMark {
  page: number;
  bbox: Anchor["bbox"];
  color: string;
}

const NO_MARKS: PdfMark[] = [];

interface Props {
  docId: string;
  highlight: Anchor | null;
  marks?: PdfMark[];
  /** 每次值变化时滚动到 highlight（定位来自重排视图时） */
  scrollKey: number;
  onPoint: (page: number, x: number, y: number) => void;
  onError: (message: string) => void;
  style?: React.CSSProperties;
}

interface PageSize {
  width: number;
  height: number;
}

export function PdfView({ docId, highlight, marks, scrollKey, onPoint, onError, style }: Props) {
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
        // 并行取：逐页 await 要和 worker 往返 numPages 次，长文档首屏会等很久
        const list: PageSize[] = await Promise.all(
          Array.from({ length: doc.numPages }, (_, i) =>
            doc.getPage(i + 1).then((p) => {
              const vp = p.getViewport({ scale: 1 });
              return { width: vp.width, height: vp.height };
            }),
          ),
        );
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

  const maxPageWidth = Math.max(1, ...sizes.map((s) => s.width));
  const maxRef = useRef(maxPageWidth);
  maxRef.current = maxPageWidth;
  const scale = width ? fitScale(width, maxPageWidth) : 1;

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    // 页面框尺寸每帧跟上（不经过 React）；重新渲染（width 状态）第一次立即、之后防抖
    let t: ReturnType<typeof setTimeout> | undefined;
    let first = true;
    const ro = new ResizeObserver(() => {
      el.style.setProperty("--pdf-scale", String(fitScale(el.clientWidth, maxRef.current)));
      clearTimeout(t);
      if (first) {
        first = false;
        setWidth(el.clientWidth);
      } else t = setTimeout(() => setWidth(el.clientWidth), RESIZE_DEBOUNCE);
    });
    ro.observe(el);
    return () => {
      clearTimeout(t);
      ro.disconnect();
    };
  }, []);

  // 页数 / 页宽载入后补一次（ResizeObserver 首次回调时页面尺寸可能还没到）
  useLayoutEffect(() => {
    const el = container.current;
    if (el) el.style.setProperty("--pdf-scale", String(fitScale(el.clientWidth, maxPageWidth)));
  }, [maxPageWidth]);

  useEffect(() => {
    if (!highlight || !container.current) return;
    const page = container.current.querySelector<HTMLElement>(`[data-page="${highlight.page}"]`);
    if (!page) return;
    const k = parseFloat(container.current.style.getPropertyValue("--pdf-scale")) || scale;
    const top = page.offsetTop + highlight.bbox[1] * k - container.current.clientHeight / 3;
    container.current.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    pulse(page.querySelector(".pdf-highlight"));
    // 只在 scrollKey 变化时滚动；PDF 内点击产生的高亮不滚动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollKey]);

  const marksByPage = useMemo(() => {
    const out = new Map<number, PdfMark[]>();
    for (const m of marks ?? []) out.set(m.page, [...(out.get(m.page) ?? []), m]);
    return out;
  }, [marks]);

  return (
    <div className="reader-pane pdf-view" ref={container} style={style}>
      {pdf &&
        sizes.map((s, i) => (
          <PdfPage
            key={i}
            pdf={pdf}
            index={i}
            size={s}
            scale={scale}
            highlight={highlight?.page === i ? highlight.bbox : null}
            marks={marksByPage.get(i) ?? NO_MARKS}
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
  marks: PdfMark[];
  onPoint: (page: number, x: number, y: number) => void;
}

function PdfPage({ pdf, index, size, scale, highlight, marks, onPoint }: PageProps) {
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
      // 画到离屏 canvas，完成后一次性拷过去：直接改可见 canvas 的宽高会先清空它，渲染期间是白页
      const off = document.createElement("canvas");
      off.width = Math.floor(viewport.width);
      off.height = Math.floor(viewport.height);
      task = page.render({ canvas: off, viewport });
      task.promise.then(
        () => {
          const c = canvas.current;
          if (cancelled || !c) return;
          c.width = off.width;
          c.height = off.height;
          c.getContext("2d")?.drawImage(off, 0, 0);
          off.width = off.height = 0;
        },
        () => undefined, // 取消渲染会 reject
      );
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [visible, pdf, index, scale]);

  // 离开预渲染范围就交还像素缓冲；回来时由上面的 effect 重新渲染
  useEffect(() => {
    if (visible || !canvas.current) return;
    canvas.current.width = 0;
    canvas.current.height = 0;
    void pdf.getPage(index + 1).then((page) => page.cleanup());
  }, [visible, pdf, index]);

  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    // 用页面框的实际宽度换算：拖动途中 --pdf-scale 已经变了，scale（渲染用）还没跟上
    const rect = e.currentTarget.getBoundingClientRect();
    const k = rect.width / size.width;
    onPoint(index, (e.clientX - rect.left) / k, (e.clientY - rect.top) / k);
  };

  return (
    <div
      ref={wrapper}
      className="pdf-page"
      data-page={index}
      style={{ width: px(size.width), height: px(size.height), marginBottom: PAGE_GAP }}
      onClick={click}
    >
      <canvas ref={canvas} aria-label={`第 ${index + 1} 页`} />
      {marks.map((m, i) => (
        <div
          key={i}
          className="pdf-mark"
          data-color={m.color}
          style={{ left: px(m.bbox[0], -7), top: px(m.bbox[1]), height: px(m.bbox[3] - m.bbox[1]) }}
        />
      ))}
      {highlight && (
        <div
          className="pdf-highlight"
          style={{
            left: px(highlight[0], -2),
            top: px(highlight[1], -2),
            width: px(highlight[2] - highlight[0], 4),
            height: px(highlight[3] - highlight[1], 4),
          }}
        />
      )}
    </div>
  );
}

/** PDF 点 → CSS 长度，跟随容器上的 --pdf-scale */
function px(points: number, offset = 0) {
  return `calc(${points}px * var(--pdf-scale, 1) + ${offset}px)`;
}
