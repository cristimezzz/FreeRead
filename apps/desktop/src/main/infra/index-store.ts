import { DatabaseSync } from 'node:sqlite';
import { createHash } from 'node:crypto';
import { existsSync, renameSync } from 'node:fs';
import { segmentForFts, SCHEMA_SQL as schema } from '@freeread/core';
import type { DocMeta, DocAnchorModel, Annotation, IpcPayloads } from '@freeread/core';
import { fail } from './files';

export class IndexStore {
  readonly db: DatabaseSync;
  readonly recovered: boolean;
  constructor(path: string) {
    const result = openDatabase(path);
    this.db = result.db; this.recovered = result.recovered;
    const version = this.db.prepare('PRAGMA user_version').get()?.['user_version'];
    if (typeof version === 'number' && version > 1) throw fail('FR-STORE-021');
    this.db.exec(schema);
    this.db.prepare('INSERT OR IGNORE INTO schema_migrations VALUES (1,?,?,?)')
      .run('m1-initial', 0, createHash('sha256').update(schema).digest('hex'));
  }
  transaction(fn: () => void) {
    this.db.exec('BEGIN IMMEDIATE');
    try { fn(); this.db.exec('COMMIT'); } catch (cause) { this.db.exec('ROLLBACK'); throw cause; }
  }
  rebuild(items: Array<{ meta: DocMeta; model: DocAnchorModel | null }>) {
    this.transaction(() => {
      this.db.exec("DELETE FROM document; DELETE FROM annotation; INSERT INTO doc_fts(doc_fts) VALUES('delete-all')");
      for (const item of items) this.put(item.meta, item.model);
    });
  }
  put(meta: DocMeta, model: DocAnchorModel | null) {
    const reading = meta.reading;
    const { readProgress: progress, readState } = this.progress(meta);
    this.db.prepare(`INSERT OR REPLACE INTO document
      (doc_id,citekey,title,authors,year,venue,doi,arxiv_id,page_count,language,quality,source_kind,
       added_at,updated_at,parser_engine,parser_version,read_state,read_progress,last_page,last_sentence_id)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(meta.docId, meta.citekey, meta.title,
      JSON.stringify(meta.authors), ...optionalColumns(meta), meta.source.kind,
      Date.parse(meta.addedAt), Date.parse(meta.updatedAt), model?.engine.name ?? null, model?.engine.version ?? null,
      readState, progress, reading?.page ?? null, reading?.sentenceId ?? null);
    this.db.prepare('DELETE FROM document_tag WHERE doc_id=?').run(meta.docId);
    this.db.prepare('DELETE FROM document_collection WHERE doc_id=?').run(meta.docId);
    for (const tag of meta.tags) this.db.prepare('INSERT INTO document_tag VALUES (?,?)').run(meta.docId, tag);
    for (const c of meta.collections) this.db.prepare('INSERT INTO document_collection VALUES (?,?)').run(meta.docId, c);
  }
  fts(items: Array<{ meta: DocMeta; model: DocAnchorModel | null }>) {
    this.transaction(() => {
      this.db.exec("INSERT INTO doc_fts(doc_fts) VALUES('delete-all')");
      for (const { meta, model } of items) this.db.prepare('INSERT INTO doc_fts(rowid,title,abstract,body) VALUES (?,?,?,?)')
        .run(parseInt(meta.docId.slice(0, 12), 16), segmentForFts(meta.title), segmentForFts(meta.abstract ?? ''),
          segmentForFts(model?.sentences.map((s) => s.text).join(' ') ?? ''));
    });
  }
  matches(query: string): Set<string> {
    const terms = segmentForFts(query).split(' ').filter(Boolean);
    if (!terms.length) return new Set();
    const match = terms.map((s) => `"${s.replaceAll('"', '""')}"`).join(' AND ');
    const rows = this.db.prepare('SELECT rowid FROM doc_fts WHERE doc_fts MATCH ?').all(match);
    return new Set(rows.map((r) => Number(r['rowid']).toString(16).padStart(12, '0')));
  }
  annotation(a: Annotation) {
    this.db.prepare('INSERT OR REPLACE INTO annotation VALUES (?,?,?,?,?,?,?,?,?,?)').run(a.id, a.docId,
      a.kind, a.anchor?.page ?? 1, a.anchor?.blockId ?? null, a.anchor?.sentenceId ?? null,
      JSON.stringify(a), Date.parse(a.createdAt), Date.parse(a.updatedAt ?? a.createdAt), a.deleted ? 1 : 0);
  }
  progress(meta: DocMeta): Pick<IpcPayloads['NotesUpdateProgressResponse'], 'readProgress' | 'readState'> {
    const readProgress = Math.min(1, ((meta.reading?.page ?? 1) - 1 + (meta.reading?.scrollRatio ?? 0)) / (meta.pageCount ?? 1));
    return { readProgress, readState: readProgress >= 0.99 ? 'read' : meta.reading ? 'reading' : 'unread' };
  }
}

function openDatabase(path: string): { db: DatabaseSync; recovered: boolean } {
  let db: DatabaseSync | undefined;
  try {
    db = new DatabaseSync(path);
    if (db.prepare('PRAGMA integrity_check').get()?.['integrity_check'] !== 'ok') throw fail('FR-STORE-004');
    return { db, recovered: false };
  } catch (cause) {
    db?.close();
    console.warn(fail('FR-STORE-004', cause).toWire());
    if (!existsSync(path)) throw fail('FR-STORE-004', cause);
    const backup = `${path}.corrupt-${Date.now()}`;
    renameSync(path, backup);
    for (const suffix of ['-wal', '-shm']) if (existsSync(path + suffix)) renameSync(path + suffix, backup + suffix);
    return { db: new DatabaseSync(path), recovered: true };
  }
}

function optionalColumns(meta: DocMeta): Array<string | number | null> {
  return [meta.year ?? null, meta.venue ?? null, meta.doi ?? null, meta.arxivId ?? null,
    meta.pageCount ?? 1, meta.language ?? null, meta.quality ?? null];
}
