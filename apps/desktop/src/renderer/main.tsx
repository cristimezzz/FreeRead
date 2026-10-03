import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LibraryView } from './views/LibraryView';
import { ReaderBoundary } from './views/ReaderBoundary';
import { translator } from './i18n/text';
import { unwrap, errorKey } from './ipc/api';
import './shell.css';
// eslint-disable-next-line no-restricted-syntax -- Boundary review: fixed local renderer module; its dependencies use window.fr only.
const ReaderView = lazy(() => import('./views/ReaderView').then((module) => ({ default: module.ReaderView })));
function App() {
  const [locale, setLocale] = useState<'zh-CN' | 'en'>('zh-CN'), [error, setError] = useState('');
  const [route, setRoute] = useState(location.hash);
  const t = translator(locale), onError = useCallback((key: string) => setError(key), []);
  useEffect(() => { void unwrap(window.fr.app.doctor({ rebuildIndex: false, fixSafe: false, pruneOrphans: false, verifyHashes: false }))
    .then((r) => { if (r.checks[0]?.code) onError(`errors.${r.checks[0].code}`); }).catch((e: unknown) => onError(errorKey(e))); }, [onError]);
  useEffect(() => {
    const update = () => setRoute(location.hash); window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  document.documentElement.lang = locale; document.title = t('app.shell.title');
  const citekey = route.startsWith('#/reader/') ? route.slice('#/reader/'.length) : '';
  return <div className="fr-app"><header className="fr-app-header"><span className="fr-wordmark">{t('app.shell.title')}</span>
    <span className="fr-local-status">{t('app.local')}</span><button onClick={() => setLocale(locale === 'zh-CN' ? 'en' : 'zh-CN')}>{t('app.shell.language')}</button></header>
    {error && <div role="alert" className="fr-error"><span>{t(error)}</span><button onClick={() => setError('')}>{t('common.dismiss')}</button></div>}
    {citekey ? <ReaderBoundary key={citekey} t={t} onError={onError} onClose={() => { location.hash = '/library'; }}>
      <Suspense fallback={<main className="fr-loading" aria-busy="true">{t('reader.loading')}</main>}>
        <ReaderView citekey={citekey} t={t} onClose={() => { location.hash = '/library'; }} onError={onError} />
      </Suspense></ReaderBoundary>
      : <LibraryView t={t} onOpen={(key) => { location.hash = '/reader/' + key; }} onError={onError} />}</div>;
}
const root = document.getElementById('root');
if (root) createRoot(root).render(<App />);
