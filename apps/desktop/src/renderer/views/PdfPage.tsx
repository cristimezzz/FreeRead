import { useEffect, useRef } from 'react';
import { TextLayer } from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { DocAnchorModel, Annotation } from '@freeread/core';
import type { Text } from '../i18n/text';
import { errorKey } from '../ipc/api';

type Props = { pdf: PDFDocumentProxy; page: number; scale: number; model: DocAnchorModel;
  annotations: Annotation[]; focused: string; t: Text; onFocus: (id: string) => void; onError: (key: string) => void };
export function PdfPage(props: Props) {
  const canvas = useRef<HTMLCanvasElement>(null), text = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!canvas.current || !text.current) return;
    const target = canvas.current, layer = text.current;
    let stopped = false, cancel = () => undefined as void;
    void props.pdf.getPage(props.page).then(async (page) => {
      if (stopped) return;
      const viewport = page.getViewport({ scale: props.scale });
      target.width = Math.ceil(viewport.width * 1.5); target.height = Math.ceil(viewport.height * 1.5);
      const task = page.render({ canvas: target, viewport, transform: [1.5, 0, 0, 1.5, 0, 0] });
      cancel = () => task.cancel();
      await task.promise;
      if (stopped) return;
      layer.replaceChildren();
      const content = await page.getTextContent();
      const textLayer = new TextLayer({ textContentSource: content, container: layer, viewport });
      cancel = () => { task.cancel(); textLayer.cancel(); };
      await textLayer.render();
      if (!stopped) mapSentences(textLayer, props.model, props.page);
    }).catch((cause: unknown) => { if (!stopped) props.onError(errorKey(cause)); });
    return () => { stopped = true; cancel(); target.width = 0; target.height = 0; layer.replaceChildren(); };
  }, [props.pdf, props.page, props.scale, props.model, props.onError]);
  return <div className="fr-pdf-content" style={{ '--scale-factor': props.scale, '--total-scale-factor': props.scale } as React.CSSProperties}>
    <canvas ref={canvas} aria-label={`${props.t('reader.page')} ${props.page}`} />
    <div ref={text} className="textLayer" onClick={(event) => {
      const node = (event.target as HTMLElement).closest<HTMLElement>('[data-sentence-id]');
      if (node?.dataset['sentenceId']) props.onFocus(node.dataset['sentenceId']);
    }} onFocus={(event) => {
      const id = (event.target as HTMLElement).dataset['sentenceId']; if (id) props.onFocus(id);
    }} />
    <div className="fr-highlight-layer" aria-hidden="true">{props.annotations.filter((a) => a.anchor?.page === props.page && !a.deleted)
      .flatMap((a) => a.anchor?.rects.map((rect, i) => <span key={`${a.id}-${i}`} className={`fr-highlight fr-highlight-${a.color ?? 'yellow'}`}
        style={{ left: rect.x * props.scale, top: rect.y * props.scale, width: rect.w * props.scale, height: rect.h * props.scale }} />))}
      {props.model.blocks.filter((b) => b.page === props.page && props.model.sentences.some((s) => s.blockId === b.id && s.id === props.focused))
        .map((b) => <span key={b.id} className="fr-focus-mark" style={{ left: b.rect.x * props.scale, top: b.rect.y * props.scale,
          width: b.rect.w * props.scale, height: b.rect.h * props.scale }} />)}</div>
  </div>;
}

function mapSentences(layer: TextLayer, model: DocAnchorModel, page: number) {
  const unused = model.blocks.filter((b) => b.page === page);
  layer.textDivs.forEach((div, index) => {
    const original = layer.textContentItemsStr[index] ?? '';
    const position = unused.findIndex((b) => b.text === original.normalize('NFC'));
    const block = unused.splice(position, position < 0 ? 0 : 1)[0];
    if (!block) return;
    div.replaceChildren();
    for (const sentence of model.sentences.filter((s) => s.blockId === block.id)) {
      const span = document.createElement('span');
      span.className = 'fr-pdf-sentence'; span.dataset['sentenceId'] = sentence.id;
      span.tabIndex = 0; span.setAttribute('role', 'button');
      span.textContent = original.slice(sentence.lines[0]?.begin ?? 0, (sentence.lines[0]?.begin ?? 0) + (sentence.lines[0]?.len ?? 0));
      span.addEventListener('keydown', (event) => { if (event.key === 'Enter') span.click(); });
      div.append(span);
    }
  });
}
