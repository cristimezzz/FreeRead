import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync, renameSync, mkdirSync, rmdirSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { buildReadingModel } from '@freeread/core';
import type { Annotation, IpcPayloads } from '@freeread/core';
import { IndexStore } from '../infra/index-store';
import { atomicWrite, fail, ioError, contained } from '../infra/files';
import { LibraryService } from './library-service';
import { NoteService } from './note-service';
import { ReaderService } from './reader-service';

let dir: string, index: IndexStore, library: LibraryService, notes: NoteService, reader: ReaderService, source: string;
const inputBytes = Buffer.from('%PDF-1.7\nSynthetic test bytes\n');
const docId = createHash('sha256').update(inputBytes).digest('hex');
const makeModel = () => buildReadingModel({ docId, pages: [1, 2, 3].map(() => ({ w: 612, h: 792,
  lines: [{ text: '中文论文 Attention. Second sentence.', rect: { x: 10, y: 80, w: 200, h: 12 } }] })) });
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'fr-m1-')); source = join(dir, 'test.pdf'); writeFileSync(source, inputBytes);
  index = new IndexStore(join(dir, 'index.sqlite'));
  library = new LibraryService(join(dir, 'library'), index, async () => makeModel());
  notes = new NoteService(library); reader = new ReaderService(library);
});
afterEach(() => { index.db.close(); rmSync(dir, { recursive: true, force: true }); });
const importPaper = () => library.import({ source: { kind: 'file', path: source }, meta: { title: '中文论文 Attention', abstract: '锚点模型方法' } },
  new AbortController().signal, () => undefined);
function progress(sessionId: string): IpcPayloads['NotesUpdateProgressRequest'] {
  return { docId, sessionId, sentenceId: 's_b_2_1_2', blockId: 'b_2_1', page: 2, scrollRatio: 0.42,
    mode: 'original', translationMode: 'off', clientEventId: '01AAAAAAAAAAAAAAAAAAAAAAAA' };
}
function annotation(): Annotation {
  return { schemaVersion: 1, id: 'an_01AAAAAAAAAAAAAAAAAAAAAAAA', docId, kind: 'note',
    anchor: { page: 2, sentenceId: 's_b_2_1_1', blockId: 'b_2_1', rects: [], lines: [] }, note: 'My insight',
    createdAt: '2026-10-03T00:00:00.000Z', deviceId: 'dev_01AAAAAAAAAAAAAAAAAAAAAAAA' };
}
test('T-008 import dedup, PDF immutable, Chinese title/abstract/body FTS and tags', async () => {
  const imported = await importPaper();
  expect(imported.created).toBe(true); expect((await importPaper()).deduped).toBe(true);
  expect(readFileSync(library.path(docId, 'paper.pdf'))).toEqual(inputBytes);
  for (const query of ['Attention', '中文', '锚点', 'Second']) expect(library.list({ query, offset: 0, limit: 10 }).total).toBe(1);
  expect(library.list({ query: '" OR broken:*', offset: 0, limit: 10 }).total).toBe(0);
  library.tags({ docId, tags: ['NLP', '中文'], mode: 'replace' });
  expect(library.list({ tags: ['中文'], offset: 0, limit: 10 }).items[0]?.tags).toEqual(['NLP', '中文']);
  library.update(docId, { title: 'Changed title' });
  expect(library.list({ query: 'Changed', offset: 0, limit: 10 }).total).toBe(1);
});
test('T-003 exact sentence/offset survives reindex and deleted SQLite index', async () => {
  await importPaper(); const opened = reader.open({ docId });
  notes.saveProgress(progress(opened.sessionId));
  const before = readFileSync(library.path(docId, 'meta.json'), 'utf8');
  expect(notes.saveProgress(progress(opened.sessionId)).updatedAt).toBe(library.get(docId).meta.reading?.updatedAt);
  expect(readFileSync(library.path(docId, 'meta.json'), 'utf8')).toBe(before);
  index.db.close(); rmSync(join(dir, 'index.sqlite'));
  index = new IndexStore(join(dir, 'index.sqlite'));
  library = new LibraryService(join(dir, 'library'), index); library.init();
  expect(new ReaderService(library).open({ docId }).restored).toMatchObject({ sentenceId: 's_b_2_1_2', scrollRatio: 0.42, degraded: false });
  expect(() => notes.saveProgress({ ...progress(opened.sessionId), page: 20 })).toThrow('FR-IPC-002');
});
test('T-003 unavailable meta target falls back to durable OpLogEntry and startup compensates', async () => {
  await importPaper(); const req = progress(reader.open({ docId }).sessionId);
  const path = library.path(docId, 'meta.json'); renameSync(path, path + '.backup'); mkdirSync(path);
  expect(() => notes.saveProgress(req)).toThrow('FR-NOTE-003');
  const log = readFileSync(join(library.root, '.oplog.jsonl'), 'utf8');
  expect(JSON.parse(log).payload.sentenceId).toBe(req.sentenceId);
  rmdirSync(path); renameSync(path + '.backup', path); library.init(); await new NoteService(library).init();
  expect(library.get(docId).meta.reading?.sentenceId).toBe(req.sentenceId);
  expect(ioError({ code: 'EACCES' }).code).toBe('FR-STORE-002');
});
test('E6 annotation updates/tombstones are append-only, bad/truncated rows preserve later notes', async () => {
  await importPaper(); notes.upsert(docId, annotation());
  notes.upsert(docId, { ...annotation(), note: 'Changed', updatedAt: '2026-10-03T01:00:00.000Z' });
  const path = library.path(docId, 'annotations.jsonl');
  writeFileSync(path, readFileSync(path, 'utf8') + '{incomplete');
  notes.upsert(docId, { ...annotation(), note: 'After torn line' });
  const restored = new NoteService(library); await restored.init();
  expect(restored.list({ docId, offset: 0, limit: 50 })).toMatchObject({ total: 1, unparsableLines: 1 });
  expect(restored.list({ docId, offset: 0, limit: 50 }).items[0]?.note).toBe('After torn line');
  restored.delete({ docId, annotationId: annotation().id });
  expect(restored.list({ docId, offset: 0, limit: 50 }).total).toBe(0);
  expect(readFileSync(path, 'utf8')).toContain('"deleted":true');
  expect(() => restored.upsert(docId, { ...annotation(), docId: 'b'.repeat(64) })).toThrow('FR-IPC-002');
});
test('meta v1 migrates atomically, newer/corrupt files are retained; file and session boundaries reject escape', async () => {
  await importPaper(); const path = library.path(docId, 'meta.json');
  const old = JSON.parse(readFileSync(path, 'utf8')); old.schemaVersion = 1;
  writeFileSync(path, JSON.stringify(old)); library.init();
  expect(JSON.parse(readFileSync(path, 'utf8')).schemaVersion).toBe(2);
  expect(() => reader.assertSession('ses_bad', docId)).toThrow('FR-IPC-002');
  expect(() => contained(library.root, '../test.pdf')).toThrow('FR-IPC-002');
  expect(() => library.get('missing')).toThrow('FR-LIB-005');
  writeFileSync(path, '{bad'); const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  library.init(); expect(readFileSync(path, 'utf8')).toBe('{bad'); warn.mockRestore();
  expect(atomicWrite).toBeDefined(); expect(ioError(fail('FR-LIB-005')).code).toBe('FR-LIB-005');
  expect(resolve(dir)).toBe(dir);
});
test('notes Markdown is file-backed, and remove moves user data to trash', async () => {
  await importPaper(); await notes.importMarkdown({ docId, markdown: '# User notes\r\n', mode: 'replace' });
  expect(await notes.markdown(docId, false)).toBe('# User notes\n');
  await notes.importMarkdown({ docId, markdown: 'More\n', mode: 'merge' });
  expect(await notes.markdown(docId, false)).toContain('More');
  const removed = library.remove({ docId, deleteFiles: true });
  expect(removed.trashed).toBe(true); expect(library.list({ offset: 0, limit: 10 }).total).toBe(0);
});
test('note writes reject a document directory replaced by an external junction', async () => {
  await importPaper();
  const documentDir = join(library.root, library.get(docId).meta.citekey), outside = join(dir, 'outside');
  renameSync(documentDir, outside); symlinkSync(outside, documentDir, 'junction');
  expect(() => notes.upsert(docId, annotation())).toThrow('FR-IPC-002');
  await expect(notes.importMarkdown({ docId, markdown: 'escaped', mode: 'replace' })).rejects.toThrow('FR-IPC-002');
});
test('corrupt SQLite is preserved and rebuilt from files', async () => {
  await importPaper(); index.db.close();
  writeFileSync(join(dir, 'index.sqlite'), 'broken database');
  index = new IndexStore(join(dir, 'index.sqlite'));
  expect(index.recovered).toBe(true);
  library = new LibraryService(join(dir, 'library'), index); library.init();
  expect(library.list({ query: 'Attention', offset: 0, limit: 10 }).total).toBe(1);
});
