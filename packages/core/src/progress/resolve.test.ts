import { expect, test } from 'vitest';
import { buildReadingModel, resolveProgress, migrateMeta, makeCitekey, segmentForFts } from '../index';

const docId = 'a'.repeat(64);
const page = { w: 612, h: 792, lines: [{ text: 'Hello. World!', rect: { x: 10, y: 20, w: 100, h: 12 } }] };
test('reading anchors are deterministic, ordered, cover raw ranges and reject bad input', () => {
  const m = buildReadingModel({ docId, pages: [page] });
  expect(buildReadingModel({ docId, pages: [page] })).toEqual(m);
  expect(m.sentences.map((s) => s.lines[0]?.len).reduce((a, b) => a + (b ?? 0), 0)).toBe(13);
  expect(() => buildReadingModel({ docId: '../escape', pages: [] })).toThrow('FR-ANCHOR-009');
  const edge = buildReadingModel({ docId, pages: [{ ...page, lines: [
    { text: ' ', rect: { x: 0, y: 0, w: 0, h: 0 } },
    { text: 'Right', rect: { x: 620, y: 800, w: 10, h: 10 } },
    { text: 'Second', rect: { x: 40, y: 20, w: 10, h: 10 } }, ...page.lines] }] });
  expect(edge.blocks.map((b) => b.text)).toEqual(['Hello. World!', 'Second', 'Right']);
  expect(edge.blocks[2]?.rect).toEqual({ x: 612, y: 792, w: 0, h: 0 });
});
test('restores exact sentence and ratio, falls back visibly for missing anchors and out-of-range pages', () => {
  const m = buildReadingModel({ docId, pages: [page] });
  expect(resolveProgress(undefined, m).degraded).toBe(false);
  const reading = { sentenceId: 's_b_1_1_2', blockId: 'b_1_1', page: 1, scrollRatio: 0.7,
    mode: 'original' as const, translationMode: 'off' as const, updatedAt: 1, clientEventId: '0'.repeat(26) };
  expect(resolveProgress(reading, m)).toMatchObject({ sentenceId: reading.sentenceId, scrollRatio: 0.7, degraded: false });
  expect(resolveProgress({ ...reading, sentenceId: 'missing', page: 50 }, m)).toMatchObject({ page: 1, degraded: true });
  const empty = buildReadingModel({ docId, pages: [{ ...page, lines: [] }] });
  expect(resolveProgress(reading, empty)).toMatchObject({ page: 1, degraded: true });
  expect(resolveProgress(undefined, { ...empty, pageSize: {} }).page).toBe(1);
});
test('migrates v1 without mutating input; leaves newer versions for boundary rejection', () => {
  const old = { schemaVersion: 1, title: 'paper' };
  expect(migrateMeta(old)).toEqual({ ...old, schemaVersion: 2 });
  expect(old.schemaVersion).toBe(1);
  for (const value of [null, 'x', { schemaVersion: 2 }, { schemaVersion: 3 }]) expect(migrateMeta(value)).toBe(value);
});
test('citekeys and shared CJK segmentation are stable', () => {
  const meta = { docId, authors: [{ family: 'Vaswani', given: '' }], year: 2017, title: 'Attention Is All You Need' };
  expect(makeCitekey(meta, new Set())).toBe('vaswani2017attention');
  expect(makeCitekey(meta, new Set(['vaswani2017attention', 'vaswani2017attention-2']))).toBe('vaswani2017attention-3');
  expect(makeCitekey({ docId, authors: [], title: '中文' }, new Set())).toBe('doc-aaaaaaaa');
  expect(makeCitekey({ docId, authors: [{ family: '张', given: '' }], title: 'Éclair' }, new Set(), 'abcdef')).toBe('abcdefndeclair');
  expect(segmentForFts('中文论文 Attention')).toContain('Attention');
  expect(segmentForFts('Hello, world!', 'en')).toBe('Hello world');
});
