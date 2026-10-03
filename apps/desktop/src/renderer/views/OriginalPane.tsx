import { useCallback, useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';
import type { DocAnchorModel, Annotation } from '@freeread/core';
import { PdfPage } from './PdfPage';
import type { Text } from '../i18n/text';
import { errorKey } from '../ipc/api';

GlobalWorkerOptions.workerSrc = workerUrl;
type Props = { url: string; model: DocAnchorModel; page: number; ratio: number; focused: string;
  annotations: Annotation[]; t: Text; onFocus: (id: string) => void; onScroll: (page: number, ratio: number) => void;
  onError: (key: string) => void; onReady: (ready: boolean) => void; zoom: number };
export function OriginalPane(props: Props) {
  const root = useRef<HTMLDivElement>(null);
  const userScrolled = useRef(false);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null), [width, setWidth] = useState(640);
  const [visible, setVisible] = useState(new Set([props.page]));
  const [readyPages, setReadyPages] = useState(new Set<number>());
  const pageReady = useCallback((page: number, ready: boolean) => setReadyPages((old) => {
    if (old.has(page) === ready) return old;
    const next = new Set(old); if (ready) next.add(page); else next.delete(page); return next;
  }), []);
  const focusedPage = props.model.sentences.find((s) => s.id === props.focused)?.page;
  useEffect(() => props.onReady(focusedPage !== undefined && readyPages.has(focusedPage)), [focusedPage, readyPages, props.onReady]);
  const pages = Object.keys(props.model.pageSize).map(Number);
  useEffect(() => {
    const task = getDocument({ url: props.url, useSystemFonts: true,
      disableAutoFetch: true, disableStream: true });
    let active = true;
    void task.promise.then((doc) => { if (active) setPdf(doc); }).catch((e: unknown) => { if (active) props.onError(errorKey(e)); });
    return () => { active = false; void task.destroy(); };
  }, [props.url, props.onError]);
  useEffect(() => {
    const node = root.current; if (!node) return;
    const resize = new ResizeObserver(() => setWidth(Math.max(280, node.clientWidth - 48)));
    resize.observe(node);
    const observer = new IntersectionObserver((entries) => setVisible((old) => {
      const next = new Set(old);
      for (const entry of entries) { const n = Number((entry.target as HTMLElement).dataset['page']);
        if (entry.isIntersecting) next.add(n); else next.delete(n); }
      return next;
    }), { root: node, rootMargin: '250px' });
    node.querySelectorAll('[data-page]').forEach((page) => observer.observe(page));
    return () => { resize.disconnect(); observer.disconnect(); };
  }, [props.model]);
  useEffect(() => {
    const node = root.current, page = node?.querySelector<HTMLElement>(`[data-page="${props.page}"]`);
    if (node && page) node.scrollTop = page.offsetTop - node.offsetTop + page.offsetHeight * props.ratio;
  }, [props.page, props.ratio, width, props.zoom]);
  return <div ref={root} className="fr-reader-area" tabIndex={0} aria-label={props.t('reader.original')}
    onWheel={() => { userScrolled.current = true; }} onPointerDown={() => { userScrolled.current = true; }}
    onKeyDown={() => { userScrolled.current = true; }} onScroll={(event) => {
    if (!userScrolled.current) return;
    const node = event.currentTarget;
    const current = Array.from(node.querySelectorAll<HTMLElement>('[data-page]')).find((page) => page.offsetTop - node.offsetTop + page.offsetHeight > node.scrollTop + 20);
    if (current) props.onScroll(Number(current.dataset['page']), Math.max(0, Math.min(1, (node.scrollTop - current.offsetTop + node.offsetTop) / current.offsetHeight)));
  }}>
    {pages.map((page) => { const size = props.model.pageSize[String(page)]; if (!size) return null;
      const scale = Math.min(width / size.w, 1.7) * props.zoom;
      return <div key={page} data-page={page} className="fr-pdf-page" style={{ width: size.w * scale, height: size.h * scale }}>
        {pdf && visible.has(page) && <PdfPage pdf={pdf} model={props.model} page={page} scale={scale} t={props.t}
          annotations={props.annotations} focused={props.focused} onFocus={props.onFocus} onError={props.onError} onReady={pageReady} />}
      </div>; })}
  </div>;
}
