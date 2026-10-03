import { useEffect, useRef, useState } from 'react';
import type { Text } from '../i18n/text';
import { OriginalPane } from './OriginalPane';
import { NotesPanel } from './NotesPanel';
import { addAnnotation, useReader } from './use-reader';
import { errorKey, unwrap } from '../ipc/api';

type Props = { citekey: string; t: Text; onClose: () => void; onError: (key: string) => void };
export function ReaderView(p: Props) {
  const state = useReader(p.citekey, p.onError), [zoom, setZoom] = useState(1), [notesOpen, setNotesOpen] = useState(false);
  const [highlightReady, setHighlightReady] = useState(false);
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const add = async (kind: 'highlight' | 'note' | 'bookmark', note?: string) => {
    if (kind === 'highlight' && !highlightReady) return;
    try { await addAnnotation(state, kind, note); } catch (e) { p.onError(errorKey(e)); }
  };
  const close = async () => {
    try { await state.save(); if (state.session) await unwrap(window.fr.doc.close({ sessionId: state.session.sessionId })); p.onClose(); }
    catch (e) { p.onError(errorKey(e)); }
  };
  useEffect(() => {
    const flush = () => { void state.save().catch((e: unknown) => p.onError(errorKey(e))); };
    window.addEventListener('beforeunload', flush); document.addEventListener('visibilitychange', flush);
    const keys = (e: KeyboardEvent) => {
      if (isEditing(e.target)) return;
      if ((e.ctrlKey || e.metaKey) && e.key === 'w') { e.preventDefault(); void close(); }
      if (e.key === 'h') void add('highlight');
      if (e.key === 'm') { setNotesOpen(true); setTimeout(() => document.getElementById('fr-note-input')?.focus(), 0); }
      if (e.key === 'Escape') setNotesOpen(false);
      if (e.key === 'j' || e.key === 'k') {
        stepSentence(state, e.key);
      }
    };
    window.addEventListener('keydown', keys);
    return () => { window.removeEventListener('beforeunload', flush); document.removeEventListener('visibilitychange', flush); window.removeEventListener('keydown', keys); };
  });
  const scroll = (page: number, ratio: number) => {
    state.position.current = { ...state.position.current, page, ratio };
    clearTimeout(scrollTimer.current);
    scrollTimer.current = setTimeout(() => {
      const height = state.model?.pageSize[String(page)]?.h ?? 1;
      const block = state.model?.blocks.find((b) => b.page === page && b.rect.y + b.rect.h > ratio * height);
      const id = state.model?.sentences.find((s) => s.blockId === block?.id)?.id;
      if (id) state.focus(id); else void state.save().catch((e: unknown) => p.onError(errorKey(e)));
    }, 500);
  };
  useEffect(() => () => clearTimeout(scrollTimer.current), []);
  if (!state.session || !state.model) return <main className="fr-loading" aria-busy="true">{p.t('reader.loading')}</main>;
  return <main className="fr-reader">
    <header className="fr-reader-toolbar"><button onClick={() => void close()}>{p.t('reader.back')}</button>
      <strong title={p.citekey}>{p.citekey}</strong><span className="fr-mode">{p.t('reader.original')}</span>
      <button onClick={() => setZoom(Math.max(0.5, zoom - 0.1))} aria-label={p.t('reader.zoom.out')}>−</button>
      <button onClick={() => setZoom(Math.min(2, zoom + 0.1))} aria-label={p.t('reader.zoom.in')}>+</button>
      <button aria-pressed={notesOpen} onClick={() => setNotesOpen(!notesOpen)}>{p.t('notes.title')}</button></header>
    <p className="fr-banner">{p.t('reader.banner.quickMode')}{state.session.restored.degraded && ` · ${p.t('reader.banner.positionRestoredDegraded')}`}</p>
    <div className="fr-reader-columns"><ReaderNavigation state={state} t={p.t} />
      <OriginalPane url={state.session.pdfUrl} model={state.model} page={state.jump.page} ratio={state.jump.ratio}
        focused={state.focused} annotations={state.items} t={p.t} onFocus={state.focus} onScroll={scroll} zoom={zoom} onError={p.onError} onReady={setHighlightReady} />
      <div className={`fr-notes-container ${notesOpen ? 'fr-panel-open' : ''}`}><NotesPanel docId={state.session.docId} items={state.items} t={p.t} onAdd={add}
        canHighlight={highlightReady} onJump={state.navigate} onError={p.onError} onDelete={(id) => {
          void unwrap(window.fr.notes.delete({ docId: state.session?.docId ?? '', annotationId: id })).then(state.refresh).catch((e: unknown) => p.onError(errorKey(e)));
        }} /></div></div>
    <footer className="fr-status" data-focused-sentence={state.focused} data-saved={state.saved}>{p.t('reader.page')} {state.currentPage} / {state.session.pageCount}
      <span>{p.t(state.saved ? 'reader.progress.saved' : 'reader.progress.restored')}</span></footer>
  </main>;
}

function ReaderNavigation({ state, t }: { state: ReturnType<typeof useReader>; t: Text }) {
  const [find, setFind] = useState('');
  return <aside className="fr-reader-navigation"><label>{t('reader.find')}<input type="search" value={find} onChange={(e) => setFind(e.target.value)} /></label>
    {find && <ul>{state.model?.sentences.filter((s) => s.text.toLowerCase().includes(find.toLowerCase())).slice(0, 50)
      .map((s) => <li key={s.id}><button onClick={() => state.navigate(s.id)}>{s.page} · {s.text}</button></li>)}</ul>}
    <label>{t('reader.page')}<input type="number" min={1} max={state.session?.pageCount} defaultValue={state.jump.page} onKeyDown={(e) => {
      if (e.key === 'Enter') { const page = Number(e.currentTarget.value); const s = state.model?.sentences.find((s) => s.page === page); if (s) state.navigate(s.id); }
    }} /></label><p>{t('reader.keyboard')}</p></aside>;
}

function isEditing(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
}
function stepSentence(state: ReturnType<typeof useReader>, key: string) {
  const sentences = state.model?.sentences ?? [], index = sentences.findIndex((s) => s.id === state.focused);
  const sentence = sentences[index + (key === 'j' ? 1 : -1)]; if (sentence) state.navigate(sentence.id);
}
