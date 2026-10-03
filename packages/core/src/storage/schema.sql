-- schema.sql — FreeRead SQLite 索引（可重建；真源见 specs/05-storage.md §1）
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
PRAGMA user_version = 1;                      -- 必须等于 schema_migrations.MAX(version)

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL,
  applied_at INTEGER NOT NULL,                 -- UTC 毫秒
  checksum   TEXT    NOT NULL                  -- sha256(迁移函数源码)
);

CREATE TABLE IF NOT EXISTS document (
  doc_id         TEXT    PRIMARY KEY,          -- sha256(paper.pdf) hex 小写 64
  citekey        TEXT    NOT NULL UNIQUE,
  title          TEXT    NOT NULL,
  authors        TEXT    NOT NULL,             -- JSON 数组字符串（与 meta.json#authors 同构）
  year           INTEGER,
  venue          TEXT,
  doi            TEXT,
  arxiv_id       TEXT,
  page_count     INTEGER,
  language       TEXT,
  quality        TEXT,                         -- native | ocr | mixed | NULL
  parser_engine  TEXT,                         -- docling | marker | grobid | rule
  parser_version TEXT,
  rules_revision INTEGER,
  source_kind    TEXT,                         -- local-file | arxiv | pmc | unpaywall | zotero | url
  added_at       INTEGER NOT NULL,
  updated_at     INTEGER NOT NULL,
  read_state     TEXT    NOT NULL DEFAULT 'unread',   -- unread | reading | read
  read_progress  REAL    NOT NULL DEFAULT 0,          -- 0..1
  last_page      INTEGER,
  last_sentence_id TEXT,
  deleted        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_document_citekey    ON document(citekey);
CREATE INDEX IF NOT EXISTS idx_document_updated_at ON document(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_document_live       ON document(updated_at DESC) WHERE deleted = 0;

CREATE TABLE IF NOT EXISTS document_tag (
  doc_id TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  tag    TEXT NOT NULL,
  PRIMARY KEY (doc_id, tag)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS document_collection (
  doc_id     TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  collection TEXT NOT NULL,
  PRIMARY KEY (doc_id, collection)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS citekey_alias (
  old_citekey TEXT PRIMARY KEY,
  new_citekey TEXT NOT NULL,
  doc_id      TEXT NOT NULL,
  changed_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS annotation (
  id          TEXT    PRIMARY KEY,             -- an_<ulid>
  doc_id      TEXT    NOT NULL,
  kind        TEXT    NOT NULL,                -- highlight | note | bookmark | ink
  page        INTEGER NOT NULL,
  block_id    TEXT,
  sentence_id TEXT,
  json        TEXT    NOT NULL,                -- 该 JSONL 行原文（逐字节，便于回写与审计）
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER,
  deleted     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_annotation_doc      ON annotation(doc_id, kind, page);
CREATE INDEX IF NOT EXISTS idx_annotation_sentence ON annotation(sentence_id);
CREATE INDEX IF NOT EXISTS idx_annotation_live     ON annotation(doc_id, updated_at DESC) WHERE deleted = 0;

CREATE TABLE IF NOT EXISTS translation_cache (
  doc_id        TEXT    NOT NULL,
  lang          TEXT    NOT NULL,
  unit          TEXT    NOT NULL,              -- paragraph | sentence
  unit_id       TEXT    NOT NULL,
  source_hash   TEXT    NOT NULL,              -- sha256(NFC + trim + 空白折叠)，见 §5 T2
  target        TEXT    NOT NULL,
  provider_id   TEXT    NOT NULL,              -- ollama | openai-compatible | none | …
  model_id      TEXT    NOT NULL DEFAULT '',   -- 具体模型；none 时为空串
  glossary_hash TEXT    NOT NULL DEFAULT '',   -- 术语表指纹；无术语表为空串
  cache_key     TEXT    NOT NULL,              -- sha256(source_hash|provider_id|model_id|glossary_hash)
  created_at    INTEGER NOT NULL,
  last_used_at  INTEGER NOT NULL,
  hits          INTEGER NOT NULL DEFAULT 0,
  bytes         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (doc_id, lang, cache_key)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_translation_hash ON translation_cache(doc_id, lang, source_hash);
CREATE INDEX IF NOT EXISTS idx_translation_lru  ON translation_cache(last_used_at);

CREATE TABLE IF NOT EXISTS op_log (
  client_event_id TEXT    PRIMARY KEY,         -- ulid()，客户端生成，同步去重键
  doc_id          TEXT,
  op              TEXT    NOT NULL,            -- import | rename | note.add | note.update | note.delete | patch.add | meta.update | reindex
  payload         TEXT    NOT NULL DEFAULT '{}',
  device_id       TEXT    NOT NULL,
  at              INTEGER NOT NULL,
  synced          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_log_at   ON op_log(at DESC);
CREATE INDEX IF NOT EXISTS idx_op_log_doc  ON op_log(doc_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_op_log_sync ON op_log(synced) WHERE synced = 0;

-- 全文检索（external content：正文真源仍在 blocks.json，表内不复制正文）
CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
  title, abstract, body,
  content='',
  tokenize='unicode61 remove_diacritics 2'
);
