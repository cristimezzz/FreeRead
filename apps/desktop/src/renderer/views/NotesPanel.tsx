import { useEffect, useState } from 'react';
import type { Annotation } from '@freeread/core';
import type { Text } from '../i18n/text';
import { errorKey, unwrap } from '../ipc/api';

type Props = { docId: string; items: Annotation[]; t: Text; onAdd: (kind: 'highlight' | 'note' | 'bookmark', note?: string) => Promise<void>;
  onDelete: (id: string) => void; onJump: (id: string) => void; onError: (key: string) => void };
export function NotesPanel(p: Props) {
  const [note, setNote] = useState(''), [markdown, setMarkdown] = useState('');
  useEffect(() => { void unwrap(window.fr.notes.exportMarkdown({ docId: p.docId, includeAnnotations: false, saveTo: 'none' }))
    .then((r) => setMarkdown(r.markdown)).catch((e: unknown) => p.onError(errorKey(e))); }, [p.docId, p.onError]);
  return <aside className="fr-notes-panel" aria-label={p.t('notes.title')}>
    <h2>{p.t('notes.title')}</h2><div className="fr-note-actions">
      <button onClick={() => void p.onAdd('highlight')}>{p.t('notes.highlight')}</button>
      <button onClick={() => void p.onAdd('bookmark')}>{p.t('notes.bookmark')}</button></div>
    <label>{p.t('notes.new')}<textarea id="fr-note-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={p.t('notes.placeholder')} /></label>
    <button className="fr-primary" disabled={!note.trim()} onClick={() => void p.onAdd('note', note).then(() => setNote(''))}>{p.t('notes.add')}</button>
    {!p.items.length && <p className="fr-muted">{p.t('notes.empty')}</p>}
    <ul className="fr-annotation-list">{p.items.map((a) => <li key={a.id}>
      <button onClick={() => p.onJump(a.anchor?.sentenceId ?? '')}>{p.t(`notes.kind.${a.kind}`)} · {p.t('reader.page')} {a.anchor?.page}</button>
      {a.quote && <blockquote>{a.quote}</blockquote>}{a.note && <p>{a.note}</p>}
      <button className="fr-subtle" onClick={() => p.onDelete(a.id)}>{p.t('common.delete')}</button></li>)}</ul>
    <label>{p.t('notes.markdown')}<textarea value={markdown} onChange={(e) => setMarkdown(e.target.value)} onBlur={() => {
      void unwrap(window.fr.notes.importMarkdown({ docId: p.docId, markdown: markdown || '\n', mode: 'replace' }))
        .catch((e: unknown) => p.onError(errorKey(e)));
    }} /></label>
    <button onClick={() => void unwrap(window.fr.notes.exportMarkdown({ docId: p.docId, includeAnnotations: true, saveTo: 'dialog' }))
      .catch((e: unknown) => p.onError(errorKey(e)))}>{p.t('notes.export')}</button>
  </aside>;
}
