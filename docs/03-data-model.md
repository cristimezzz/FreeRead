# 数据模型

- 版本：0.2（M1 已实现部分与代码同步）
- 更新日期：2026-10-20
- 决策依据：[ADR-0002](adr/0002-local-first-sqlite.md)
- 实现：SQLAlchemy 2.x 模型 + Alembic 迁移（`core/freeread/infra/db/`）

**实现状态**：迁移 `0001_initial_m1_schema` 建了 13 张表——items、collections、item_collections、item_tags、attachments、sync_state、documents、blocks、translations、jobs、llm_cache、llm_calls、settings；迁移 `0002_embeddings_fts`（M2）加了 embedding_chunks 和 FTS5 表 blocks_fts，向量表 vec_chunks_<dim> 运行时创建；迁移 `0003_summaries` 加了 summaries；迁移 `0004_qa` 加了 qa_sessions、qa_nodes；迁移 `0005_glossary` 加了 glossary_terms；迁移 `0006_annotations` 加了 annotations。下文标"计划"的表（kg_*）和 items_fts 还没有建，结构仍是草案，实现时以迁移为准再回来更新本文。

## 1. 总览

```
items ─┬─< attachments ──1:1── documents ─┬─< blocks ─┬─< translations
       │                                  │           ├─< embedding_chunks ── vec_chunks_<dim>
       ├─< item_collections >─ collections│           └─< annotations
       └─< item_tags                      ├─< summaries
                                          └─< kg_relations(source)
（计划，M2+）
kg_entities ─< kg_entity_aliases
kg_entities ─< kg_relations >─ kg_entities
qa_sessions ─< qa_nodes (自引用 parent_id)
glossary_terms
jobs
llm_calls      llm_cache
settings       sync_state
```

约定：

- 主键使用文本 ID（ULID 或文档内 ID），时间戳统一为 UTC ISO8601 文本。例外：`translations.id` 是自增整数。
- JSON 字段使用 SQLite `TEXT` 存储，在应用层校验。
- 每个连接启用 `PRAGMA foreign_keys = ON`、`journal_mode = WAL`、`synchronous = NORMAL`、`busy_timeout = 5000`（`infra/db/engine.py`）。
- 约束命名：`pk_<表>`、`fk_<表>_<列>_<被引用表>`、`uq_<表>_<列…>`、`ix_<表>_<列…>`（SQLAlchemy naming convention，便于 Alembic batch 迁移）。
- 下文"FK"未注明时，删除被引用行会级联删除（`ON DELETE CASCADE`）；注明 SET NULL 的置空。
- IR 全文以文件形式保存在 `documents/<doc_id>/ir.json`，`blocks` 表是它的可查询副本。

## 2. 文献库

### items
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| zotero_key | TEXT UNIQUE NULL | Zotero 条目 key |
| zotero_library_id | TEXT NULL | 用户库或群组库 |
| zotero_version | INTEGER NULL | 用于增量同步 |
| item_type | TEXT | journalArticle、preprint 等；Zotero 里没有父条目的独立 PDF 为 `attachment`（`extra.standalone = true`） |
| title | TEXT | |
| authors | JSON NOT NULL | `[{"first","last"}]` |
| year | INTEGER NULL | |
| doi | TEXT NULL | |
| venue | TEXT NULL | |
| abstract | TEXT NULL | |
| extra | JSON NOT NULL | 其他 Zotero 字段 |
| status | TEXT | `active` / `archived`（Zotero 里已删除的条目同步后归档，不物理删除） |
| created_at / updated_at | TEXT | |

索引：`ix_items_doi`、`ix_items_title`。FTS5 虚拟表 `items_fts(title, abstract, authors)`：计划，M1 的文献库搜索直接查 items。

### collections / item_collections / item_tags
| 表 | 列 |
|---|---|
| collections | id PK, zotero_key UNIQUE NULL, name, parent_id NULL（FK → collections，SET NULL） |
| item_collections | item_id FK, collection_id FK（联合主键） |
| item_tags | item_id FK, tag（联合主键） |

### attachments
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | |
| item_id | TEXT FK → items | 索引 |
| zotero_key | TEXT UNIQUE NULL | 手动导入的 PDF 为空 |
| path | TEXT | 本地绝对路径 |
| content_type | TEXT | `application/pdf` |
| sha256 | TEXT NULL | 首次读取时计算 |
| doc_id | TEXT NULL FK → documents（SET NULL） | 读取文件、算出 sha256 后关联（同一 PDF 多个附件共用一个 document）；索引 |

### sync_state
| 列 | 说明 |
|---|---|
| source PK | `zotero_local`（M1 只实现了这一种）；计划：`zotero_sqlite` / `zotero_web:<library_id>` |
| last_version | INTEGER NULL，最后同步的 Zotero library version |
| last_synced_at | TEXT NULL |

## 3. 文档与块

### documents
| 列 | 类型 | 说明 |
|---|---|---|
| doc_id | TEXT PK | `d_` + sha256 前 16 位 |
| pdf_sha256 | TEXT UNIQUE | |
| page_count | INTEGER NULL | 解析后填写 |
| ir_path | TEXT NULL | 相对数据目录：`documents/<doc_id>/ir.json` |
| ir_schema_version | TEXT NULL | |
| parser_engine / parser_version / normalizer_version | TEXT NULL | 当前 IR 来自哪个引擎；自动流程不会用低等级引擎的结果覆盖高等级的（ADR-0003） |
| parse_status | TEXT | `pending` / `parsing` / `ready` / `failed`；已有 IR 时重新解析失败会回到 `ready` |
| embed_status | TEXT | `pending / embedding / ready / failed`；嵌入来源不可用时保持 `pending` |
| kg_status | TEXT | 同 parse_status；M3 前恒为 `pending` |
| language | TEXT NULL | |
| created_at / updated_at | TEXT | |

### blocks
| 列 | 类型 | 说明 |
|---|---|---|
| doc_id | TEXT FK → documents | 联合主键之一 |
| block_id | TEXT | 联合主键之一 |
| ord | INTEGER | 阅读顺序 |
| type | TEXT | 见 IR 块类型 |
| section_id | TEXT NULL | |
| text | TEXT | 含占位符 |
| inlines | JSON | |
| latex / html / label | TEXT NULL | |
| anchors | JSON | |
| content_hash | TEXT | |

索引：`ix_blocks_doc_id_ord`、`ix_blocks_content_hash`。重新解析时整篇替换（与写 ir.json 在同一事务）。FTS5 `blocks_fts`：见下。

### blocks_fts（FTS5 虚拟表）
```sql
CREATE VIRTUAL TABLE blocks_fts USING fts5(
  text, doc_id UNINDEXED, block_id UNINDEXED, tokenize='trigram'
);
```
每个可检索块（可翻译类型 + 表格）一行，`text` 是展开占位符后的纯文本（行内公式换成 LaTeX，表格取单元格文本）。trigram 分词对中文不需要分词，少于 3 个字符的查询词退回 `LIKE`。独立存内容，不用 external content：`blocks` 是复合主键，隐式 rowid 在 VACUUM 后可能变。与 `blocks` 在同一事务里替换（`ParseService._store`）。

### embedding_chunks
| 列 | 类型 | 说明 |
|---|---|---|
| rowid | INTEGER PK | 对应向量表的 `chunk_rowid` |
| doc_id | TEXT FK → documents ON DELETE CASCADE | |
| ord | INTEGER | 文档内顺序 |
| block_ids | JSON | 覆盖的块；短块合并、长块拆分，所以是多对多 |
| model | TEXT | 嵌入来源，如 `local/multilingual-e5-small`、`<provider_id>/<model>` |
| text_hash | TEXT | chunk 文本的 sha256；重新解析后文本没变的 chunk 直接复用旧向量 |
| text | TEXT | 送去嵌入的文本（section 标题 + 块文本） |

索引：`ix_embedding_chunks_doc_id_ord`、`ix_embedding_chunks_model_text_hash`。

### vec_chunks_<dim>（sqlite-vec 虚拟表，运行时创建）
```sql
CREATE VIRTUAL TABLE vec_chunks_384 USING vec0(
  chunk_rowid integer primary key,   -- embedding_chunks.rowid
  doc_id text partition key,         -- 按文档检索时只扫这一篇
  embedding float[384] distance_metric=cosine,
  chunk_size=128                     -- 每个分区至少占一个块；默认 1024 对单篇论文太大
);
```
维度随模型而定，所以不在迁移里建，由 `SqliteVecIndex.ensure` 按第一批向量的维度创建；当前模型和维度记在 `settings` 的内部键 `_vector_index`。表名带维度：WAL 模式下在显式事务里 DROP vec0 表会报 `SQL logic error`，所以换模型时只清空，旧维度的空表由 `drop_unused` 在 autocommit 连接上删除。

### annotations
高亮与批注（[M2 批注](m2/annotations.md)）。没有单独的 kind：有 note 的就是批注。原版视图没有文字层，按块的 anchors 画标记。

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| doc_id | TEXT FK→documents ON DELETE CASCADE | |
| block_id | TEXT | 不做外键：重新解析时按块映射迁移 |
| start, end | INTEGER NULL | 块 text（含 `⟦KEY⟧` 占位符）里的字符区间；都为空表示整块 |
| quote | TEXT | 区间里的原文，重新解析后用于重新定位 |
| color | TEXT | `yellow` / `green` / `blue` / `pink` / `purple` |
| note | TEXT | 批注内容，可为空 |
| status | TEXT | `ok` / `stale`（重新解析后找不到原文；批注保留） |
| created_at, updated_at | TEXT | |

索引：`ix_annotations_doc_id_block_id`。

## 4. 翻译

### translations
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增 |
| doc_id | TEXT FK → documents | |
| block_id, lang | TEXT | `(doc_id, block_id, lang, model, prompt_version)` 联合唯一；block_id 不设外键，重新解析时按 IR §8 迁移，迁移不了的标 `stale` |
| model | TEXT | provider/model |
| prompt_version | TEXT | 如 `translate@1` |
| text | TEXT | 含占位符的译文 |
| status | TEXT | `ok` / `needs_review`（占位符校验失败，回退原文）/ `stale` |
| is_active | BOOLEAN | 同一块同一语言当前显示的版本 |
| created_at | TEXT | |

索引：`ix_translations_doc_id_lang_block_id`。

### glossary_terms
术语表（[M2 术语表](m2/glossary.md)）。翻译时只注入在块里出现的条目；文档条目覆盖全局同名条目。

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| scope | TEXT | `global` / `doc:<doc_id>`（以后可能有 `collection:<id>`） |
| doc_id | TEXT NULL FK→documents ON DELETE CASCADE | 文档条目的文档；全局条目为空。只用于删除文档时级联 |
| lang | TEXT | 目标语言 |
| source_term | TEXT | 原文术语（按用户 / 模型写法保存） |
| term_key | TEXT | 归一化的原文术语（合并空白、casefold），用于去重 |
| target_term | TEXT | 译法 |
| note | TEXT | 说明，如缩写的全称 |
| origin | TEXT | `user` / `auto`（自动抽取）。用户改过的 auto 条目变成 user，重新抽取不覆盖 |
| created_at, updated_at | TEXT | |

唯一约束 `(scope, lang, term_key)`。

## 5. 总结

### summaries
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| doc_id | TEXT FK → documents ON DELETE CASCADE | |
| scope | TEXT | `doc:<doc_id>`；以后的分类级综述为 `collection:<id>` |
| template_id | TEXT | `paper`、`brief`（`core/prompts/templates/summary.yaml`） |
| lang | TEXT | 总结语言 |
| model | TEXT | `provider/model` |
| prompt_version | TEXT | 如 `summarize_map@1+summarize_reduce@1+paper@1` |
| content | JSON | `{sections: [{key, name, points: [{text, block_ids: ["b_0012"], untraced?}]}]}`；块属于本行的文档，API 不再拼 `doc_id#` |
| stats | JSON | `points / cited_points / coverage / invalid_ids / groups / failed_groups / elapsed_ms` |
| status | TEXT | `ok` / `stale`（重新解析后有引用映射不上） |
| created_at | TEXT | |

唯一约束 `(doc_id, template_id, lang)`：每种模板每种语言只保留最新一份，重新生成时替换。重新解析时与译文在同一事务里按 IR §8 的块映射改写引用（`services/summary.migrate_summaries`）。

## 6. 知识图谱（计划）

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

M2 实现了单篇线性对话（迁移 `0004_qa`）。M3 的问答画布会在 `qa_nodes` 上加 `pinned_blocks`、`subgraph`、`position`（设计见架构 §5.7B），`parent_id` 已经能表示分叉。

### qa_sessions
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| doc_id | TEXT FK → documents ON DELETE CASCADE | M2 只有单篇；分类 / 全库问答时改为可空 |
| scope | TEXT | `doc:<doc_id>`；以后有 `collection:<id>`、`library` |
| title | TEXT | 首个问题的前 40 个字 |
| created_at / updated_at | TEXT | 每问一次更新 `updated_at`，列表按它倒序 |

索引 `ix_qa_sessions_doc_id_updated_at`。

### qa_nodes
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | ULID |
| session_id | TEXT FK → qa_sessions ON DELETE CASCADE | |
| parent_id | TEXT FK → qa_nodes ON DELETE SET NULL | 上一轮；M2 为线性链 |
| question | TEXT | |
| answer | TEXT | 引用写成 `[b_0012]`，已校验都存在于该文档（块属于会话的文档，不再拼 `doc_id#`） |
| citations | JSON | 按首次出现顺序的块 ID |
| stats | JSON | `invalid_ids`（模型编造、已删除的编号数）/ `out_of_context` / `context_ids` / `modes` / `elapsed_ms` |
| model / prompt_version | TEXT | `provider/model`、`qa_answer@1` |
| status | TEXT | `ok` / `stale`（重新解析后有引用映射不上） |
| created_at | TEXT | |

索引 `ix_qa_nodes_session_id_created_at`。重新解析时与译文、总结在同一事务里改写引用（`services/qa.migrate_qa`）。

## 8. 基础设施

### jobs
| 列 | 说明 |
|---|---|
| id PK | |
| kind | M1：`sync`、`parse`（快速模式，并发 2）、`parse_hq`（MinerU / Docling，全局并发 1）；计划：`embed` / `kg_extract` / `translate_doc` / `summarize`。块级翻译不走任务队列，由 `POST /translate/blocks` 以 SSE 流式完成 |
| payload | JSON |
| status | `queued` / `running` / `done` / `failed` / `cancelled` |
| progress | REAL 0–1 |
| message | 当前进度说明 |
| depends_on NULL | 前置 job id（FK → jobs，SET NULL） |
| attempts, error | |
| created_at, started_at, finished_at | |

索引：`ix_jobs_status_created_at`（worker 按创建顺序取 queued 任务）。

### llm_cache
| 列 | 说明 |
|---|---|
| key PK | `sha256(provider|model|prompt_id@version|canonical_input)`；嵌入按单条文本，prompt_id 为 `embed@1` |
| response | JSON：`{text, model, usage}`；嵌入为 `{embedding}` |
| created_at, hit_count | |

### llm_calls
`id (ULID), task_kind, provider, model, prompt_id NULL, input_tokens, output_tokens, cost_estimate NULL, latency_ms, cache_hit (BOOLEAN), doc_id NULL, created_at`；索引 `ix_llm_calls_doc_id`。

每次成功的调用写一行；缓存命中 `cache_hit=1` 且 token 记 0。`cost_estimate` 暂不计算（NULL）。

### settings
`key PK, value JSON`。每个顶层设置项一行，键即 `AppSettings` 的字段名：`appearance`、`target_lang`、`parse_engine`、`providers`、`routes`、`consented_providers`、`embedding`（`services/settings.py`）。以 `_` 开头的键是内部状态（如 `_vector_index`），不属于设置。读取时不认识的键忽略，单个字段不合法时回退默认值。**API Key 不存这里**，存在系统钥匙串（由壳以 `FREEREAD_SECRETS` 注入 sidecar）。

## 9. 迁移策略

- 所有结构变更通过 Alembic 迁移（`infra/db/migrations/versions/`，当前 head 为 `0004`）；应用启动时自动升级，已有数据时升级前备份为 `freeread.db.bak-<旧版本>`。打包版的迁移脚本随 sidecar 一起分发（`scripts/build_sidecar.ps1`）。
- 更换嵌入来源 / 模型时清空向量索引和 embedding_chunks，所有文档 `embed_status` 置回 `pending` 并重新排队（`EmbedService.enqueue_missing`，启动和保存设置时调用）。
- IR 主版本升级见 [02-document-ir.md §9](02-document-ir.md)。
