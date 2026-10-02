import type { DocMeta } from '../meta.generated';

const STOPWORDS = new Set('a an the of on in for and or to with from by at is are new all you need as into its this that these those using via toward towards over'.split(' '));
export function makeCitekey(meta: Pick<DocMeta, 'authors' | 'year' | 'title' | 'docId'>, taken: ReadonlySet<string>, familyHash = meta.docId.slice(0, 6)): string {
  const family = meta.authors.length ? meta.authors[0]?.family.toLowerCase().match(/[a-z]+/)?.[0] ?? familyHash : 'anon';
  const word = meta.title.toLowerCase().normalize('NFKD').replace(/[^a-z0-9 ]/g, '')
    .split(/\s+/).find((w) => w && !STOPWORDS.has(w)) ?? '';
  const base = !word && family === 'anon' ? `doc-${meta.docId.slice(0, 8)}`
    : `${family}${meta.year ?? 'nd'}${word}`.slice(0, 40);
  let key = base;
  for (let n = 2; taken.has(key); n++) key = `${base.slice(0, 40 - String(n).length - 1)}-${n}`;
  return key;
}
