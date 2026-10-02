import { existsSync, createReadStream, readdirSync, statSync, lstatSync, renameSync } from 'node:fs';
import { copyFile, open } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { basename, join, resolve } from 'node:path';
import { migrateMeta, makeCitekey } from '@freeread/core';
import type { DocMeta, DocAnchorModel, IpcPayloads } from '@freeread/core';
import { createFileValidator } from '../ipc/validate';
import { IndexStore } from '../infra/index-store';
import { atomicWrite, docPath, ensureDirectory, readJson, fail, contained, ulid } from '../infra/files';
import { extractPdf } from './extract';

const metaValidator = createFileValidator<DocMeta>('meta.schema.json');
const modelValidator = createFileValidator<DocAnchorModel>('doc-anchor-model.schema.json');
export type StoredDocument = { meta: DocMeta; model: DocAnchorModel | null };

export class LibraryService {
  readonly documents = new Map<string, StoredDocument>();
  readonly warnings: string[] = [];
  constructor(readonly root: string, readonly index: IndexStore,
    readonly extract: typeof extractPdf = extractPdf) { ensureDirectory(root); }
  path(docId: string, file: string): string {
    return docPath(this.root, this.get(docId).meta.citekey, file);
  }
  get(docId: string): StoredDocument {
    const item = this.documents.get(docId);
    if (!item) throw fail('FR-LIB-005');
    return item;
  }
  init(): void {
    this.documents.clear();
    for (const dir of readdirSync(this.root, { withFileTypes: true })) {
      if (!dir.isDirectory() || dir.name.startsWith('.')) continue;
      try { this.load(dir.name); } catch (cause) {
        this.warnings.push('FR-STORE-013'); console.warn(fail('FR-STORE-013', cause).toWire());
      }
    }
    if (this.index.recovered) this.warnings.push('FR-STORE-004');
    this.index.rebuild([...this.documents.values()]);
    this.index.fts([...this.documents.values()]);
  }
  private load(citekey: string) {
    const path = docPath(this.root, citekey, 'meta.json');
    const raw = readJson(contained(this.root, path));
    const result = metaValidator.safeParse(migrateMeta(raw));
    if (!result.success || result.data.citekey !== citekey) throw fail('FR-STORE-013');
    const meta = result.data;
    const modelPath = docPath(this.root, citekey, 'blocks.json');
    let model: DocAnchorModel | null = null;
    if (existsSync(modelPath)) {
      const parsed = modelValidator.safeParse(readJson(contained(this.root, modelPath)));
      if (parsed.success && parsed.data.docId === meta.docId) model = parsed.data;
      else this.warnings.push('FR-ANCHOR-009');
    }
    this.documents.set(meta.docId, { meta, model });
    if (typeof raw === 'object' && raw !== null && Reflect.get(raw, 'schemaVersion') === 1) this.writeMeta(meta);
  }
  writeMeta(meta: DocMeta) {
    if (!metaValidator.safeParse(meta).success) throw fail('FR-STORE-013');
    contained(this.root, join(this.root, meta.citekey));
    atomicWrite(this.path(meta.docId, 'meta.json'), JSON.stringify(meta, null, 2) + '\n');
    this.get(meta.docId).meta = meta;
    try { this.index.put(meta, this.get(meta.docId).model); } catch (cause) {
      this.warnings.push('FR-STORE-005'); console.warn(fail('FR-STORE-005', cause).toWire());
    }
  }
  async import(req: IpcPayloads['LibraryImportRequest'], signal: AbortSignal, onProgress: (n: number) => void)
    : Promise<IpcPayloads['LibraryImportResponse']> {
    const path = importPath(req);
    const model = await this.extract(path, signal, onProgress);
    if (signal.aborted) throw fail('FR-NOTE-004');
    const old = this.documents.get(model.docId);
    if (old) return this.importResult(old.meta, false, true);
    const now = new Date().toISOString();
    const initial: DocMeta = { schemaVersion: 2, docId: model.docId, citekey: '',
      title: basename(path, '.pdf').normalize('NFC'), authors: [{ family: 'anonymous', given: '' }],
      tags: req.tags ?? [], collections: [], source: { kind: 'local-file' }, addedAt: now, updatedAt: now,
      pageCount: Object.keys(model.pageSize).length, quality: model.sentences.length ? 'native' : 'ocr' };
    const meta = this.patched(initial, req.meta ?? {});
    meta.citekey = req.citekey ?? makeCitekey(meta, new Set([...this.documents.values()].map((d) => d.meta.citekey)),
      createHash('sha256').update(JSON.stringify(meta)).digest('hex').slice(0, 6));
    if (existsSync(docPath(this.root, meta.citekey, 'paper.pdf'))) throw fail('FR-STORE-014');
    if (!metaValidator.safeParse(meta).success) throw fail('FR-STORE-013');
    if (!req.dryRun) await this.commitImport(path, meta, model);
    return this.importResult(meta, !req.dryRun, false);
  }
  private async commitImport(source: string, meta: DocMeta, model: DocAnchorModel) {
    const stage = join(this.root, `.import-${ulid()}`), final = join(this.root, meta.citekey);
    if (existsSync(final)) throw fail('FR-STORE-014');
    ensureDirectory(stage);
    const target = join(stage, 'paper.pdf');
    await copyFile(source, target, 1);
    const handle = await open(target, 'r+');
    try { await handle.sync(); } finally { await handle.close(); }
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(target)) hash.update(chunk);
    if (hash.digest('hex') !== meta.docId) throw fail('FR-STORE-015');
    atomicWrite(join(stage, 'blocks.json'), JSON.stringify(model));
    atomicWrite(join(stage, 'meta.json'), JSON.stringify(meta, null, 2) + '\n');
    renameSync(stage, final);
    this.documents.set(meta.docId, { meta, model });
    this.index.put(meta, model);
    this.index.fts([...this.documents.values()]);
  }
  private importResult(meta: DocMeta, created: boolean, deduped: boolean): IpcPayloads['LibraryImportResponse'] {
    return { docId: meta.docId, citekey: meta.citekey, meta, pageCount: meta.pageCount ?? 1,
      created, deduped, warnings: deduped ? ['FR-LIB-006'] : [] };
  }
  item(doc: StoredDocument): IpcPayloads['LibraryItem'] {
    const { meta, model } = doc;
    return { docId: meta.docId, citekey: meta.citekey, meta, pageCount: meta.pageCount ?? 1,
      parserEngine: model?.engine.name ?? null, parserVersion: model?.engine.version ?? null,
      ...this.index.progress(meta), tags: meta.tags, hasAnchorModel: !!model,
      hasNotes: existsSync(docPath(this.root, meta.citekey, 'annotations.jsonl')),
      present: existsSync(docPath(this.root, meta.citekey, 'paper.pdf')) };
  }
  list(req: IpcPayloads['LibraryListRequest']): IpcPayloads['LibraryListResponse'] {
    const hits = req.query ? this.index.matches(req.query) : null;
    const all = [...this.documents.values()].map((doc) => this.item(doc)).filter((doc) =>
      (!hits || hits.has(doc.docId.slice(0, 12))) && (!req.readState || doc.readState === req.readState)
      && (!req.tags?.length || (req.tagMode === 'all' ? req.tags.every((t) => doc.tags.includes(t))
        : req.tags.some((t) => doc.tags.includes(t)))));
    const sort = req.sort ?? 'addedAt';
    all.sort((a, b) => String(a.meta[sort] ?? '').localeCompare(String(b.meta[sort] ?? '')) * (req.order === 'asc' ? 1 : -1));
    return { items: all.slice(req.offset, req.offset + req.limit), total: all.length };
  }
  patched(meta: DocMeta, patch: IpcPayloads['DocMetaPatch']): DocMeta {
    const next = { ...meta, updatedAt: new Date().toISOString() };
    for (const [key, value] of Object.entries(patch)) {
      if (key === 'authors' && Array.isArray(value)) {
        const names: string[] = value;
        if (!names[0]) throw fail('FR-STORE-013');
        next.authors = [{ family: names[0], given: '' }, ...names.slice(1).map((name) => ({ family: name, given: '' }))];
      } else if (value === null) Reflect.deleteProperty(next, key);
      else Reflect.set(next, key, value);
    }
    return next;
  }
  update(docId: string, patch: IpcPayloads['DocMetaPatch']) {
    const meta = this.patched(this.get(docId).meta, patch);
    this.writeMeta(meta); this.index.fts([...this.documents.values()]);
    return { docId, meta, warnings: [] };
  }
  tags(req: IpcPayloads['LibrarySetTagsRequest']) {
    const old = this.get(req.docId).meta;
    const tags = req.mode === 'replace' ? req.tags : req.mode === 'add' ? [...new Set([...old.tags, ...req.tags])]
      : old.tags.filter((t) => !req.tags.includes(t));
    this.writeMeta({ ...old, tags, updatedAt: new Date().toISOString() });
    return { docId: req.docId, tags };
  }
  remove(req: IpcPayloads['LibraryRemoveRequest']) {
    if (!req.deleteFiles) throw fail('FR-IPC-002');
    const item = this.get(req.docId);
    ensureDirectory(join(this.root, '.trash'));
    renameSync(contained(this.root, join(this.root, item.meta.citekey)), join(this.root, '.trash', `${item.meta.citekey}-${ulid()}`));
    this.documents.delete(req.docId); this.index.rebuild([...this.documents.values()]);
    this.index.fts([...this.documents.values()]);
    return { docId: req.docId, filesDeleted: false, trashed: true, warnings: [] };
  }
}
function importPath(req: IpcPayloads['LibraryImportRequest']) {
  if (req.source.kind !== 'file') throw fail('FR-NET-003');
  const path = resolve(req.source.path);
  if (!lstatSync(path).isFile() || !path.toLowerCase().endsWith('.pdf')) throw fail('FR-LIB-004');
  if (statSync(path).size > 512 * 1024 * 1024) throw fail('FR-STORE-019');
  return path;
}
