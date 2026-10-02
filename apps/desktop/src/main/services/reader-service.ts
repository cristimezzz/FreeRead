import { createHash } from 'node:crypto';
import { resolveProgress } from '@freeread/core';
import type { IpcPayloads } from '@freeread/core';
import type { LibraryService } from './library-service';
import { contained, fail, ulid } from '../infra/files';

export class ReaderService {
  readonly sessions = new Map<string, string>();
  constructor(readonly library: LibraryService) {}
  assertSession(sessionId: string, docId: string) {
    if (this.sessions.get(sessionId) !== docId) throw fail('FR-IPC-002');
  }
  open(req: IpcPayloads['DocOpenRequest']): IpcPayloads['DocOpenResponse'] {
    const doc = req.docId ? this.library.get(req.docId)
      : [...this.library.documents.values()].find((d) => d.meta.citekey === req.citekey);
    if (!doc) throw fail('FR-LIB-005');
    contained(this.library.root, this.library.path(doc.meta.docId, 'paper.pdf'));
    const sessionId = `ses_${ulid()}`;
    this.sessions.set(sessionId, doc.meta.docId);
    const restored = doc.model ? resolveProgress(doc.meta.reading, doc.model)
      : { page: doc.meta.reading?.page ?? 1, degraded: !!doc.meta.reading, scrollRatio: doc.meta.reading?.scrollRatio ?? 0 };
    return { sessionId, docId: doc.meta.docId, citekey: doc.meta.citekey, mode: 'original',
      pageCount: doc.meta.pageCount ?? 1, engine: 'rule', anchorReady: !!doc.model,
      pdfUrl: `fr-file://${doc.meta.docId}/paper.pdf`, restored: { ...restored, mode: 'original' } };
  }
  model(req: IpcPayloads['DocGetAnchorModelRequest']): IpcPayloads['DocGetAnchorModelResponse'] {
    this.assertSession(req.sessionId, req.docId);
    const model = this.library.get(req.docId).model;
    if (!model) throw fail('FR-ANCHOR-009');
    return { docId: req.docId, model, source: 'cache',
      cacheKey: createHash('sha256').update(req.docId + model.engine.name + model.engine.version + '1' + '1').digest('hex') };
  }
  close(req: IpcPayloads['DocCloseRequest']): IpcPayloads['DocCloseResponse'] {
    if (!this.sessions.has(req.sessionId)) throw fail('FR-IPC-002');
    this.sessions.delete(req.sessionId);
    return { sessionId: req.sessionId, closed: true, progressSaved: true };
  }
}
