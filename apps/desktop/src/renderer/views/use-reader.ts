import { useCallback, useEffect, useRef, useState } from 'react';
import type { Annotation, DocAnchorModel, IpcPayloads } from '@freeread/core';
import { unwrap, newId, errorKey, uiError } from '../ipc/api';
import type { MutableRefObject } from 'react';

export type ReaderState = {
  session: IpcPayloads['DocOpenResponse'] | null; model: DocAnchorModel | null; items: Annotation[];
  focused: string; saved: boolean; currentPage: number; jump: { page: number; ratio: number };
  position: MutableRefObject<{ page: number; ratio: number; sentenceId: string; blockId: string }>;
  save: () => Promise<void>; focus: (id: string) => void; navigate: (id: string) => void; refresh: () => Promise<void>;
};

export function useReader(citekey: string, onError: (key: string) => void): ReaderState {
  const [session, setSession] = useState<IpcPayloads['DocOpenResponse'] | null>(null);
  const [model, setModel] = useState<DocAnchorModel | null>(null), [items, setItems] = useState<Annotation[]>([]);
  const [focused, setFocused] = useState(''), [saved, setSaved] = useState(false);
  const position = useRef({ page: 1, ratio: 0, sentenceId: '', blockId: '' });
  const [jump, setJump] = useState({ page: 1, ratio: 0 }), [currentPage, setCurrentPage] = useState(1);
  useEffect(() => {
    let active = true;
    void unwrap(window.fr.doc.open({ citekey, mode: 'original' })).then(async (opened) => {
      const result = await unwrap(window.fr.doc.getAnchorModel({ docId: opened.docId, sessionId: opened.sessionId }));
      if (!active) { await window.fr.doc.close({ sessionId: opened.sessionId }); return; }
      const id = opened.restored.sentenceId ?? result.model.sentences.find((s) => s.page === opened.restored.page)?.id ?? '';
      const blockId = result.model.sentences.find((s) => s.id === id)?.blockId ?? `b_${opened.restored.page}_1`;
      position.current = { page: opened.restored.page, ratio: opened.restored.scrollRatio ?? 0, sentenceId: id, blockId };
      setJump({ page: opened.restored.page, ratio: opened.restored.scrollRatio ?? 0 }); setCurrentPage(opened.restored.page);
      setSession(opened); setModel(result.model); setFocused(id);
      const notes = await unwrap(window.fr.notes.list({ docId: opened.docId, offset: 0, limit: 500 }));
      if (active) { setItems(notes.items); if (notes.unparsableLines) onError('errors.FR-NOTE-001'); }
    }).catch((e: unknown) => onError(errorKey(e)));
    return () => { active = false; };
  }, [citekey, onError]);
  const save = useCallback(async () => {
    if (!session) return;
    const p = position.current;
    setSaved(false);
    await unwrap(window.fr.notes.updateProgress({ docId: session.docId, sessionId: session.sessionId,
      mode: 'original', translationMode: 'off', page: p.page, scrollRatio: p.ratio,
      sentenceId: p.sentenceId || `s_b_${p.page}_1_1`, blockId: p.blockId || `b_${p.page}_1`, clientEventId: newId() }));
    setSaved(true);
  }, [session]);
  const focus = useCallback((id: string) => {
    const sentence = model?.sentences.find((s) => s.id === id); if (!sentence) return;
    position.current = { ...position.current, page: sentence.page, sentenceId: id, blockId: sentence.blockId };
    setFocused(id); setCurrentPage(sentence.page);
    void save().catch((e: unknown) => onError(errorKey(e)));
  }, [model, save, onError]);
  const navigate = (id: string) => {
    const sentence = model?.sentences.find((s) => s.id === id), block = model?.blocks.find((b) => b.id === sentence?.blockId);
    if (!sentence || !block) return;
    const ratio = block.rect.y / (model?.pageSize[String(sentence.page)]?.h ?? 1);
    position.current.ratio = ratio;
    setJump({ page: sentence.page, ratio }); focus(id);
  };
  const refresh = async () => {
    if (session) setItems((await unwrap(window.fr.notes.list({ docId: session.docId, offset: 0, limit: 500 }))).items);
  };
  return { session, model, items, focused, saved, position, jump, currentPage, save, focus, navigate, refresh };
}

export async function addAnnotation(state: ReturnType<typeof useReader>, kind: 'highlight' | 'note' | 'bookmark', note?: string) {
  const { session, model, focused } = state;
  const selectedId = selectionId(focused);
  const sentence = model?.sentences.find((s) => s.id === selectedId), block = model?.blocks.find((b) => b.id === sentence?.blockId);
  if (!session || !model || !sentence || !block) throw uiError('FR-STORE-017');
  const anchor: NonNullable<Annotation['anchor']> = { page: sentence.page, blockId: block.id, sentenceId: sentence.id,
    rects: kind === 'highlight' ? selectionRects(sentence.id, sentence.page, model) : [], lines: sentence.lines };
  const now = new Date().toISOString();
  const a: Annotation = { schemaVersion: 1, id: `an_${newId()}`, docId: session.docId, kind, anchor,
    createdAt: now, updatedAt: now, deviceId: 'dev_00000000000000000000000000', quote: selectedQuote(sentence.text),
    ...(kind === 'highlight' ? { color: 'yellow' } : {}), ...(note ? { note } : {}) };
  await unwrap(window.fr.notes.upsert({ docId: session.docId, sessionId: session.sessionId, annotation: a }));
  await state.refresh();
}
function selectionId(fallback: string) {
  return window.getSelection()?.anchorNode?.parentElement?.closest<HTMLElement>('[data-sentence-id]')?.dataset['sentenceId'] ?? fallback;
}
function selectedQuote(fallback: string) { return window.getSelection()?.toString().slice(0, 4096) || fallback; }

function selectionRects(id: string, page: number, model: DocAnchorModel) {
  const span = document.querySelector<HTMLElement>(`[data-sentence-id="${id}"]`);
  const paper = span?.closest<HTMLElement>('[data-page]'), size = model.pageSize[String(page)];
  if (!span || !paper || !size) return [];
  const selection = window.getSelection(), box = paper.getBoundingClientRect(), scale = box.width / size.w;
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  const rects = range && paper.contains(range.commonAncestorContainer) && selection?.toString()
    ? Array.from(range.getClientRects()) : [span.getBoundingClientRect()];
  return rects.filter((r) => r.width > 0 && r.height > 0).map((r) => ({ x: Math.max(0, (r.x - box.x) / scale),
    y: Math.max(0, (r.y - box.y) / scale), w: r.width / scale, h: r.height / scale }));
}
