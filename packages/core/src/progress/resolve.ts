import type { DocMeta } from '../meta.generated';
import type { DocAnchorModel } from '../anchor.generated';

export function resolveProgress(reading: DocMeta['reading'], model: DocAnchorModel) {
  const pages = Object.keys(model.pageSize).map(Number);
  const page = Math.min(Math.max(reading?.page ?? 1, 1), Math.max(1, ...pages));
  const sentence = model.sentences.find((s) => s.id === reading?.sentenceId)
    ?? model.sentences.find((s) => s.page === page);
  const mode = reading ? reading.mode : 'original' as const;
  return { page: sentence?.page ?? page, ...(sentence ? { sentenceId: sentence.id } : {}),
    mode, scrollRatio: reading?.scrollRatio ?? 0,
    degraded: !!reading && sentence?.id !== reading.sentenceId };
}

// Migration is pure; the file boundary validates the result before replacement.
export function migrateMeta(input: unknown): unknown {
  if (typeof input === 'object' && input !== null && Reflect.get(input, 'schemaVersion') === 1) {
    return { ...input, schemaVersion: 2 };
  }
  return input;
}
