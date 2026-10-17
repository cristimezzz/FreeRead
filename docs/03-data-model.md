# 数据模型

- 版本：0.1（草案）
- 更新日期：2026-10-17
- 决策依据：[ADR-0002](adr/0002-local-first-sqlite.md)
- 实现：SQLAlchemy 2.x 模型 + Alembic 迁移（`core/freeread/infra/db/`）

## 1. 总览

```
items ─┬─< attachments ──1:1── documents ─┬─< blocks ─┬─< translations
       │                                  │           ├─< block_embeddings
       ├─< item_collections >─ collections│           └─< annotations
       └─< item_tags                      ├─< summaries
                                          └─< kg_relations(source)
kg_entities ─< kg_entity_aliases
kg_entities ─< kg_relations >─ kg_entities
qa_sessions ─< qa_nodes (自引用 parent_id)
glossary_terms
jobs
llm_calls      llm_cache
settings       sync_state
```

约定：

- 主键使用文本 ID（ULID 或文档内 ID），时间戳统一为 UTC ISO8601 文本。
- JSON 字段使用 SQLite `TEXT` 存储，在应用层校验。
- 启用 `PRAGMA foreign_keys = ON`、`journal_mode = WAL`。
- IR 全文以文件形式保存在 `documents/<doc_id>/ir.json`，`blocks` 表是它的可查询副本。

## 2. 文献库

### items
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| zotero_key | TEXT UNIQUE NULL | Zotero 条目 key |
| zotero_library_id | TEXT NULL | 用户库或群组库 |
| zotero_version | INTEGER NULL | 用于增量同步 |
| item_type | TEXT | journalArticle、preprint 等 |
| title | TEXT | |
| authors | JSON | `[{"first","last"}]` |
| year | INTEGER NULL | |
| doi | TEXT NULL | |
| venue | TEXT NULL | |
| abstract | TEXT NULL | |
| extra | JSON | 其他 Zotero 字段 |
| status | TEXT | `active` / `archived` |
| created_at / updated_at | TEXT | |

索引：`(doi)`、`(title)`；FTS5 虚拟表 `items_fts(title, abstract, authors)`。

### collections / item_collections / item_tags
| 表 | 列 |
|---|---|
| collections | id PK, zotero_key UNIQUE NULL, name, parent_id NULL |
| item_collections | item_id, collection_id（联合主键） |
| item_tags | item_id, tag（联合主键） |

### attachments
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | |
| item_id | TEXT FK → items | |
| zotero_key | TEXT NULL | |
| path | TEXT | 本地绝对路径 |
| content_type | TEXT | `application/pdf` |
| sha256 | TEXT NULL | 首次读取时计算 |
| doc_id | TEXT NULL FK → documents | 解析后关联 |

### sync_state
| 列 | 说明 |
|---|---|
| source PK | `zotero_local` / `zotero_sqlite` / `zotero_web:<library_id>` |
| last_version | 最后同步的 Zotero library version |
| last_synced_at | |

## 3. 文档与块

### documents
| 列 | 类型 | 说明 |
|---|---|---|
| doc_id | TEXT PK | `d_` + sha256 前 16 位 |
| pdf_sha256 | TEXT UNIQUE | |
| page_count | INTEGER | |
| ir_path | TEXT | 相对数据目录 |
| ir_schema_version | TEXT | |
| parser_engine / parser_version / normalizer_version | TEXT | |
| parse_status | TEXT | `pending` / `parsing` / `ready` / `failed` |
| embed_status / kg_status | TEXT | 同上 |
| language | TEXT | |
| created_at / updated_at | TEXT | |

### blocks
| 列 | 类型 | 说明 |
|---|---|---|
| doc_id | TEXT FK | 联合主键之一 |
| block_id | TEXT | 联合主键之一 |
| ord | INTEGER | 阅读顺序 |
| type | TEXT | 见 IR 块类型 |
| section_id | TEXT NULL | |
| text | TEXT | 含占位符 |
| inlines | JSON | |
| latex / html / label | TEXT NULL | |
| anchors | JSON | |
| content_hash | TEXT | |

索引：`(doc_id, ord)`、`(content_hash)`；FTS5 `blocks_fts(text)` 用于关键词检索，与向量检索混合使用。

### block_embeddings（sqlite-vec 虚拟表）
```sql
CREATE VIRTUAL TABLE block_embeddings USING vec0(
  rowid INTEGER PRIMARY KEY,     -- 映射到 embedding_map.rowid
  embedding FLOAT[1024]          -- 维度随嵌入模型而定，换模型需重建
);
```
`embedding_map(rowid PK, doc_id, block_id, model, chunk_text_hash)`：一个块可能被切分成多个 chunk，也可能多个短块合并为一个 chunk。

### annotations
| 列 | 说明 |
|---|---|
| id PK | |
| doc_id, block_id | 关联块 |
| kind | `highlight` / `note` |
| range | JSON，块内字符区间，或 PDF 坐标 |
| color, note | |
| created_at | |

## 4. 翻译

### translations
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增 |
| doc_id, block_id, lang | | 联合唯一（加上 model, prompt_version）；block_id 不设外键，重新解析时按 IR §8 迁移 |
| model | TEXT | provider/model |
| prompt_version | TEXT | 如 `translate@3` |
| text | TEXT | 含占位符的译文 |
| status | TEXT | `ok` / `needs_review` / `stale` |
| is_active | INTEGER | 同一块同一语言当前显示的版本 |
| created_at | TEXT | |

### glossary_terms
| 列 | 说明 |
|---|---|
| id PK | |
| scope | `global` / `collection:<id>` / `doc:<doc_id>` |
| source_term, target_term, lang | |
| note | |
| origin | `user` / `auto` |

## 5. 总结

### summaries
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | |
| scope | TEXT | `doc:<doc_id>` 或 `collection:<id>` |
| template_id | TEXT | |
| model / prompt_version / lang | TEXT | |
| content | JSON | `{sections: [{name, points: [{text, citations: ["d_…#b_…"]}]}]}` |
| status | TEXT | `ok` / `stale` |
| created_at | TEXT | |

## 6. 知识图谱

### kg_entities
| 列 | 说明 |
|---|---|
| id PK | ULID |
| type | Task / Method / Dataset / Metric / Model / Concept / Claim |
| name | 规范名 |
| description | |
| embedding_rowid NULL | 名称 + 描述的向量，用于消歧 |
| created_at | |

### kg_entity_aliases
`entity_id, alias`（联合主键），以及 `alias_norm` 索引（小写、去标点）。

### kg_relations
| 列 | 说明 |
|---|---|
| id PK | |
| src_id, dst_id | FK → kg_entities |
| type | proposes / uses / improves_on / evaluated_on / achieves / compares_with / contradicts / part_of |
| attrs | JSON，如 `{"metric": "BLEU", "value": 28.4}` |
| doc_id, source_block_id | 出处（必填） |
| confidence | REAL |
| extractor | 模型 + 提示词版本 |

索引：`(src_id, type)`、`(dst_id, type)`、`(doc_id)`。

## 7. 问答

### qa_sessions
`id PK, title, scope(doc/collection/library 及其 ID), created_at, updated_at`

### qa_nodes
| 列 | 说明 |
|---|---|
| id PK | |
| session_id | FK |
| parent_id NULL | 自引用；根节点为空 |
| question | |
| answer | 含 `[d_…#b_…]` 引用标记 |
| citations | JSON：引用列表及校验结果 |
| pinned_blocks | JSON：用户固定的原文片段 |
| subgraph | JSON：本次回答涉及的实体与关系 ID |
| model / prompt_version | |
| position | JSON：画布坐标 `{x, y}` |
| created_at | |

## 8. 基础设施

### jobs
| 列 | 说明 |
|---|---|
| id PK | |
| kind | `sync` / `parse` / `embed` / `kg_extract` / `translate_doc` / `summarize` |
| payload | JSON |
| status | `queued` / `running` / `done` / `failed` / `cancelled` |
| progress | REAL 0–1 |
| message | 当前进度说明 |
| depends_on NULL | 前置 job id |
| attempts, error | |
| created_at, started_at, finished_at | |

### llm_cache
| 列 | 说明 |
|---|---|
| key PK | `sha256(provider|model|prompt_id@version|canonical_input)` |
| response | JSON |
| created_at, hit_count | |

### llm_calls
`id, task_kind, provider, model, prompt_id, input_tokens, output_tokens, cost_estimate, latency_ms, cache_hit, doc_id NULL, created_at`

### settings
`key PK, value JSON`。**API Key 不存这里**，存在系统钥匙串。

## 9. 迁移策略

- 所有结构变更通过 Alembic 迁移；应用启动时自动升级，升级前自动备份 `freeread.db`。
- 更换嵌入模型（维度变化）时，删除并重建 `block_embeddings`，作为后台任务执行。
- IR 主版本升级见 [02-document-ir.md §9](02-document-ir.md)。
