import { useEffect, useState } from 'react';
import type { IpcPayloads } from '@freeread/core';
import { unwrap, errorKey } from '../ipc/api';
import type { Text } from '../i18n/text';

export function LibraryView({ t, onOpen, onError }: { t: Text; onOpen: (citekey: string) => void; onError: (key: string) => void }) {
  const [items, setItems] = useState<IpcPayloads['LibraryItem'][]>([]);
  const [query, setQuery] = useState(''), [tag, setTag] = useState('');
  const [tags, setTags] = useState<string[]>([]), [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(''), [offset, setOffset] = useState(0), [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      unwrap(window.fr.library.list({ offset, limit: 50, ...(query.trim() ? { query: query.trim() } : {}),
        ...(tag ? { tags: [tag], tagMode: 'all' } : {}) }))
        .then((r) => { if (active) { setItems(r.items); setTotal(r.total); } }).catch((e: unknown) => onError(errorKey(e)));
      unwrap(window.fr.library.listTags({})).then((r) => { if (active) setTags(r.tags.map((a) => a.tag)); })
        .catch((e: unknown) => onError(errorKey(e)));
    }, 150);
    return () => { active = false; clearTimeout(timer); };
  }, [query, tag, offset, revision, onError]);
  const refresh = () => setRevision((n) => n + 1); const importPdfs = async () => {
    setBusy(true); setMessage('');
    try {
      const paths = await window.fr.local.pickPdf();
      for (const path of paths) {
        const result = await unwrap(window.fr.library.import({ source: { kind: 'file', path } }));
        setMessage(t(result.deduped ? 'library.import.duplicate' : 'library.import.saved')); refresh();
      }
    } catch (e) { onError(errorKey(e)); } finally { setBusy(false); } };
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') { e.preventDefault(); if (!busy) void importPdfs(); }
    };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  });
  return <main className="fr-library">
    <section className="fr-library-heading"><div><h1>{t('library.title')}</h1><p>{t('library.description')}</p></div>
      <button className="fr-primary" disabled={busy} onClick={() => void importPdfs()}>{t('library.import.button')}</button></section>
    <div className="fr-library-filters"><label>{t('library.search')}<input type="search" value={query}
      onChange={(e) => { setQuery(e.target.value); setOffset(0); }} placeholder={t('library.search.placeholder')} /></label>
      <label>{t('library.tags')}<select value={tag} onChange={(e) => { setTag(e.target.value); setOffset(0); }}>
        <option value="">{t('library.tags.all')}</option>{tags.map((name) => <option key={name}>{name}</option>)}</select></label></div>
    {busy && <div className="fr-import-status" aria-busy="true"><span>{t('library.import.busy')}</span>
      <button onClick={() => void window.fr.local.cancelImport()}>{t('common.cancel')}</button></div>}
    <p role="status">{message}</p>
    {!items.length ? <section className="fr-empty"><h2>{t(query || tag ? 'library.empty.search' : 'library.empty.title')}</h2>
      <p>{t('library.empty.description')}</p></section> : <ul className="fr-document-list">{items.map((item) =>
      <li key={item.docId}><button className="fr-document-open" onClick={() => onOpen(item.citekey)}>
        <span className="fr-document-title">{item.meta.title}</span><span className="fr-document-details">{item.citekey} · {item.pageCount} {t('library.pages')}
          · {t(`library.state.${item.readState}`)}</span></button>
        <label className="fr-tag-edit">{t('library.tags')}<input aria-label={`${t('library.tags')} ${item.citekey}`}
          defaultValue={item.tags.join(', ')} onBlur={(e) => {
            const tags = [...new Set(e.target.value.split(',').map((a) => a.trim()).filter(Boolean))];
            void unwrap(window.fr.library.setTags({ docId: item.docId, tags, mode: 'replace' })).then(refresh)
              .catch((e: unknown) => onError(errorKey(e)));
          }} /></label><button onClick={() => {
            if (window.confirm(t('library.remove.confirm'))) void unwrap(window.fr.library.remove({ docId: item.docId, deleteFiles: true }))
              .then(refresh).catch((e: unknown) => onError(errorKey(e)));
          }}>{t('library.remove')}</button></li>)}</ul>}
    <nav className="fr-pagination" aria-label={t('library.pagination')}><button disabled={!offset} onClick={() => setOffset(offset - 50)}>{t('common.previous')}</button>
      <span>{offset + items.length} / {total}</span><button disabled={offset + items.length >= total} onClick={() => setOffset(offset + 50)}>{t('common.next')}</button></nav>
  </main>;
}
