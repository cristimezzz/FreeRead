import { createReadStream, existsSync, statSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';
import { z } from 'zod';
import type { Annotation, DocMeta, IpcPayloads } from '@freeread/core';
import { createFileValidator } from '../ipc/validate';
import { appendDurable, atomicWrite, fail, ulid, contained } from '../infra/files';
import type { LibraryService } from './library-service';

const annotationValidator = createFileValidator<Annotation>('annotation.schema.json');
const metaValidator = createFileValidator<DocMeta>('meta.schema.json');
const replayValidator = z.object({ op: z.literal('progress.save'), doc_id: z.string(),
  payload: z.unknown(), client_event_id: z.string(), device_id: z.string(), at: z.number(), synced: z.number() }).strict();

export class NoteService {
  readonly deviceId: string;
  readonly annotations = new Map<string, Annotation>();
  readonly badLines = new Map<string, number>();
  constructor(readonly library: LibraryService, deviceId = `dev_${ulid()}`) { this.deviceId = deviceId; }
  async init() {
    this.annotations.clear(); this.badLines.clear();
    for (const { meta } of this.library.documents.values()) await this.load(meta.docId);
    const log = join(this.library.root, '.oplog.jsonl');
    if (existsSync(log)) await this.replay(log);
  }
  private async replay(log: string) {
    const lines = createInterface({ input: createReadStream(log), crlfDelay: Infinity });
    for await (const line of lines) {
      try {
        const event = replayValidator.safeParse(JSON.parse(line));
        if (!event.success) continue;
        const old = this.library.get(event.data.doc_id).meta;
        const meta = metaValidator.parse({ ...old, reading: event.data.payload });
        if ((meta.reading?.updatedAt ?? 0) > (old.reading?.updatedAt ?? 0)) this.library.writeMeta(meta);
      } catch (cause) { console.warn(fail('FR-NOTE-003', cause).toWire()); }
    }
  }
  async load(docId: string) {
    const path = this.library.path(docId, 'annotations.jsonl');
    if (existsSync(path)) contained(this.library.root, path);
    if (!existsSync(path)) return;
    let bad = 0;
    const lines = createInterface({ input: createReadStream(path), crlfDelay: Infinity });
    for await (const line of lines) {
      try {
        const value = annotationValidator.parse(JSON.parse(line));
        if (value.docId !== docId) throw fail('FR-NOTE-001');
        this.annotations.set(value.id, value);
      } catch (cause) { bad++; console.warn(fail('FR-NOTE-001', cause).toWire()); }
    }
    this.badLines.set(docId, bad);
    for (const a of this.annotations.values()) if (a.docId === docId) this.library.index.annotation(a);
  }
  list(req: IpcPayloads['NotesListRequest']): IpcPayloads['NotesListResponse'] {
    this.library.get(req.docId);
    const items = [...this.annotations.values()].filter((a) => a.docId === req.docId
      && (req.includeDeleted || !a.deleted) && (!req.kinds || req.kinds.some((kind) => kind === a.kind)));
    return { items: items.slice(req.offset, req.offset + req.limit), total: items.length,
      revision: items.length, unparsableLines: this.badLines.get(req.docId) ?? 0 };
  }
  upsert(docId: string, value: Annotation): IpcPayloads['NotesUpsertResponse'] {
    const annotation = annotationValidator.parse({ ...value, deviceId: this.deviceId });
    if (annotation.docId !== docId) throw fail('FR-IPC-002');
    const old = this.annotations.get(annotation.id);
    if (old && (old.docId !== docId || old.createdAt !== annotation.createdAt)) throw fail('FR-IPC-002');
    if (annotation.kind === 'highlight' && !annotation.anchor?.rects.length) throw fail('FR-IPC-002');
    const sentence = this.validateAnchor(docId, annotation);
    const path = this.library.path(docId, 'annotations.jsonl');
    if (existsSync(path) && statSync(path).size > 64 * 1024 * 1024) throw fail('FR-STORE-020');
    if (Buffer.byteLength(JSON.stringify(annotation)) > 8192) throw fail('FR-STORE-020');
    appendDurable(path, annotation);
    this.annotations.set(annotation.id, annotation);
    this.library.index.annotation(annotation);
    return { docId, annotationId: annotation.id, created: !old, orphan: !sentence };
  }
  private validateAnchor(docId: string, annotation: Annotation) {
    const model = this.library.get(docId).model;
    const sentence = model?.sentences.find((s) => s.id === annotation.anchor?.sentenceId);
    if (sentence && (sentence.page !== annotation.anchor?.page || sentence.blockId !== annotation.anchor.blockId)) throw fail('FR-IPC-002');
    return sentence;
  }
  delete(req: IpcPayloads['NotesDeleteRequest']) {
    const old = this.annotations.get(req.annotationId);
    if (!old || old.docId !== req.docId || req.hard) throw fail('FR-IPC-002');
    this.upsert(req.docId, { ...old, deleted: true, updatedAt: new Date().toISOString() });
    return { docId: req.docId, annotationId: req.annotationId, deleted: true as const };
  }
  saveProgress(req: IpcPayloads['NotesUpdateProgressRequest']): IpcPayloads['NotesUpdateProgressResponse'] {
    const item = this.library.get(req.docId), old = item.meta;
    if (req.page > (old.pageCount ?? 1)) throw fail('FR-IPC-002');
    const sentence = item.model?.sentences.find((s) => s.id === req.sentenceId);
    if (sentence && (sentence.page !== req.page || sentence.blockId !== req.blockId)) throw fail('FR-IPC-002');
    if (old.reading?.clientEventId === req.clientEventId) return {
      docId: req.docId, updatedAt: old.reading.updatedAt, ...this.library.index.progress(old) };
    const updatedAt = Date.now();
    const reading: NonNullable<DocMeta['reading']> = { page: req.page, blockId: req.blockId,
      sentenceId: req.sentenceId, scrollRatio: req.scrollRatio, mode: req.mode,
      translationMode: req.translationMode, clientEventId: req.clientEventId, updatedAt };
    try { this.library.writeMeta({ ...old, reading, updatedAt: new Date(updatedAt).toISOString() }); }
    catch (cause) {
      appendDurable(join(this.library.root, '.oplog.jsonl'), { op: 'progress.save', doc_id: req.docId,
        payload: reading, client_event_id: req.clientEventId, device_id: this.deviceId, at: updatedAt, synced: 0 });
      throw fail('FR-NOTE-003', cause);
    }
    return { docId: req.docId, updatedAt, ...this.library.index.progress(this.library.get(req.docId).meta) };
  }
  async markdown(docId: string, includeAnnotations: boolean) {
    this.library.get(docId);
    const path = this.library.path(docId, 'notes.md');
    let markdown = '';
    if (existsSync(path)) for await (const chunk of createReadStream(path, { encoding: 'utf8' })) markdown += chunk;
    if (includeAnnotations) markdown += '\n' + [...this.annotations.values()].filter((a) => a.docId === docId && !a.deleted)
      .map((a) => `> ${(a.quote ?? '').replaceAll('\n', '\n> ')}\n\n${a.note ?? ''}\n\n[${a.anchor?.page ?? 1}](freeread://doc/${this.library.get(docId).meta.citekey}#${a.anchor?.sentenceId ?? ''})\n`).join('\n');
    return markdown;
  }
  async importMarkdown(req: IpcPayloads['NotesImportMarkdownRequest']) {
    const old = req.mode === 'merge' ? await this.markdown(req.docId, false) : '';
    atomicWrite(this.library.path(req.docId, 'notes.md'), old + req.markdown.replaceAll('\r\n', '\n'));
    return { docId: req.docId, imported: 1, skipped: 0, conflicts: [] };
  }
}
