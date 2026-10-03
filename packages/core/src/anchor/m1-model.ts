import { z } from 'zod';
import type { DocAnchorModel } from '../anchor.generated';
import { AppError } from '../error';

const rect = z.object({ x: z.number().nonnegative(), y: z.number().nonnegative(),
  w: z.number().nonnegative(), h: z.number().nonnegative() }).strict();
export const readingInput = z.object({ docId: z.string().regex(/^[0-9a-f]{64}$/),
  pages: z.array(z.object({ w: z.number().positive(), h: z.number().positive(),
    lines: z.array(z.object({ text: z.string(), rect }).strict()) }).strict()).min(1) }).strict();

export function buildReadingModel(input: unknown): DocAnchorModel {
  const result = readingInput.safeParse(input);
  if (!result.success) throw new AppError('FR-ANCHOR-009', {
    category: 'parse', severity: 'error', retryable: false, i18nKey: 'errors.FR-ANCHOR-009' });
  const { docId, pages } = result.data;
  const model: DocAnchorModel = { schemaVersion: 1, docId, engine: { name: 'rule', version: 'm1-1' },
    pageSize: {}, blocks: [], paragraphs: [], sentences: [], outline: [], figures: [], references: [],
    stats: { blockCount: 0, sentenceCount: 0, lowConfidenceBlocks: 0, durationMs: 0 } };
  pages.forEach((p, index) => addPage(model, p, index + 1));
  model.stats.blockCount = model.blocks.length;
  model.stats.lowConfidenceBlocks = model.blocks.length;
  model.stats.sentenceCount = model.sentences.length;
  return model;
}

function addPage(model: DocAnchorModel, p: z.infer<typeof readingInput>['pages'][number], page: number) {
  model.pageSize[String(page)] = { w: p.w, h: p.h };
  // ponytail: text-item blocks serve original-mode anchors; M2 replaces them with layout-aware line clustering.
  const lines = p.lines.filter((line) => line.text.trim()).sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
  lines.forEach((line, lineId) => {
    const id = `b_${page}_${lineId + 1}`;
    const box = { x: Math.min(line.rect.x, p.w), y: Math.min(line.rect.y, p.h),
      w: Math.min(line.rect.w, Math.max(0, p.w - line.rect.x)),
      h: Math.min(line.rect.h, Math.max(0, p.h - line.rect.y)) };
    model.blocks.push({ id, page, rect: box, type: 'text', score: 0.5, order: model.blocks.length,
      text: line.text.normalize('NFC'), lines: [{ page, lineId, begin: 0, len: line.text.length }] });
    const sentenceIds: string[] = [];
    [...new Intl.Segmenter('en', { granularity: 'sentence' }).segment(line.text)].forEach((part, i) => {
      const sentenceId = `s_${id}_${i + 1}`;
      sentenceIds.push(sentenceId);
      model.sentences.push({ id: sentenceId, blockId: id, page, kind: 'text', text: part.segment.normalize('NFC'),
        lines: [{ lineId, page, begin: part.index, len: part.segment.length }] });
    });
    model.paragraphs.push({ id: `pa_${page}_${lineId + 1}`, blockIds: [id], sentenceIds });
  });
}
