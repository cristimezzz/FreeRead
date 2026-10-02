import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import zh from './i18n/zh-CN.json';
import en from './i18n/en.json';
import './shell.css';

function App() {
  const [locale, setLocale] = useState<'zh-CN' | 'en'>('zh-CN');
  const text = locale === 'zh-CN' ? zh : en;
  document.documentElement.lang = locale;
  document.title = text['app.shell.title'];
  return <main className="fr-shell">
    <header><h1>{text['app.shell.title']}</h1>
      <button onClick={() => setLocale(locale === 'zh-CN' ? 'en' : 'zh-CN')}>
        {text['app.shell.language']}
      </button>
    </header>
    <p className="fr-subtitle">{text['app.shell.subtitle']}</p>
    <section aria-labelledby="fr-status"><h2 id="fr-status">{text['app.shell.status']}</h2>
      <p>{text['app.shell.description']}</p>
    </section>
  </main>;
}
const root = document.getElementById('root');
if (root) createRoot(root).render(<App />);
