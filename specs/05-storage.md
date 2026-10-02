# 05 · 存储规范（文件式知识库 + SQLite 索引）

> 状态：**冻结**（2026-10-03）。上游依据：[方案 §3.4](../plan/FreeRead-技术方案与里程碑.md)（数据模型）、ADR-08（SQLite + 文件式知识库）、ADR-09（同步策略）、§9 Day 3。
> 本文定义 `library/` 布局、`annotations.jsonl` / `translation/*.jsonl` / `patches/*.json` 格式、SQLite DDL、迁移与 `freeread doctor`。
> 术语/标识符/命名遵循 `README.md` §3；锚点模型遵循 `03-anchor-model.md`（本文**不重定义** `Rect`/`LineRef`/`Block`/`Sentence`）。
> 机器可读契约：`schemas/meta.schema.json`、`schemas/annotation.schema.json`、`schemas/app-config.schema.json`。**优先级**：`schemas/*.json` > `03-anchor-model.md` > 本文 > 实现。
> 篇幅说明：正文按 300–450 行目标编写；§7 的 `schema.sql` 必须完整可直接执行（不拆分文件）且 §3.2 含错误码登记表，故总行数略超该目标。

---

## 1. 真源原则（Source of Truth）

| 项 | 规定 |
|---|---|
| 唯一真源 | `library/` 下的磁盘文件。用户数据（元数据、标注、笔记、译文、补丁）一律以文件为准 |
| 索引 | `%APPDATA%/FreeRead/index.sqlite`，**可 100% 重建**，不得含文件里没有的信息 |
| 写入顺序 | **先原子写文件（临时文件 + rename + fsync）→ 再更新索引**；索引写失败只允许"索引落后"，禁止反向。落后必须能被 `LibraryService.init()` 与 `freeread doctor --check` 检出（§9） |
| 文件被外部修改 | 合法（Git / 同步盘 / 手工编辑）；启动时**禁止**覆盖文件，以 `mtime + sha256` 检出变化后重灌索引（ADR-09 文件级冲突检测） |
| 删除语义 | 取消导入 = 删除 `library/<citekey>/` + 索引行；无回收站、无隐藏状态 |
| `library` 根 | 由 `config.json#libraryPath` 指定（默认 `~/FreeRead/library`）；整体拷贝即完成迁移 |

### 1.1 原子写协议 `atomicWriteFile(target, bytes)`（REQUIRED）

| # | 步骤 | 失败语义 |
|---|---|---|
| 1 | 内存中序列化 + schema 校验（`zod` / JSON Schema）；不通过 → `FR-STORE-013`，不落盘 | 文件与索引均不变 |
| 2 | `tmp = join(dirname(target), tmpName(target))`；**必须同目录**（跨卷 rename 非原子），命名见 §10.3 | 不变 |
| 3 | 写入全部字节 → `fh.sync()`（fsync） | 删临时文件 + `FR-STORE-012` |
| 4 | `fs.rename(tmp, target)`（同卷覆盖为原子） | 删临时文件 + `FR-STORE-012` |
| 5 | 父目录 fsync（POSIX）；Windows 无目录 fsync → 跳过并 debug 记 `storage.dirsync.skipped` | 忽略 |
| 6 | **单事务**更新 SQLite 索引 | 文件已更新、索引落后 → 写 `op_log`，下次 `--check` 修复 |
| 7 | 追加 `op_log`（`client_event_id = ulid()`） | 只丢审计，不阻断 |

**禁止**：直接 `writeFile(target, …)` 覆盖真源；先写索引再写文件；对 `paper.pdf` 做任何写操作；在两处（文件 + 索引）各存一份可独立演化的数据（索引字段必须能由文件推导）。

### 1.2 可重建性契约（必须被测试证明）

> `freeread doctor --rebuild` 在**删除 `index.sqlite`** 后重建的库，必须与重建前的"规范化转储"逐行相等（用例 `T-STORE-REBUILD`，见 `10-testing.md`）：`SELECT * FROM document ORDER BY doc_id`、`annotation ORDER BY id, updated_at`、`translation_cache ORDER BY doc_id, lang, cache_key`。

---

## 2. 知识库布局

### 2.1 完整目录树

```
<libraryPath>/                                  # 默认 ~/FreeRead/library
└─ <citekey>/                                   # 目录名 = citekey（§3），唯一
   ├─ paper.pdf                                 # 原始 PDF（只读真源）
   ├─ meta.json                                 # 元数据（schemas/meta.schema.json）
   ├─ blocks.json                               # DocAnchorModel（03-anchor-model.md，schemaVersion=1）
   ├─ notes.md                                  # 用户笔记（Markdown，UTF-8，无 BOM）
   ├─ annotations.jsonl                         # 标注（单行 JSON，追加写，§4）
   ├─ translation/{zh-CN,en}.jsonl              # 段落/句子译文缓存（§5，按语言分文件）
   ├─ patches/<ulid>.json                        # 纠错补丁（§6，ULID 文件名）
   └─ .fr-meta.json                             # 应用内部清单（可删，§2.2）
```

**路径规则**：目录名与文件名一律小写（仅语言目录允许 `zh-CN.jsonl` 形式的大写）；`citekey` 不得为 `schema.json` / `index.jsonl` / `trash` / `.fr-meta.json` 及 Windows 保留名（`con`、`prn`、`aux`、`nul`、`com1..9`、`lpt1..9`）；文件之间**只允许**用 `docId` / `citekey` / `blockId` / `sentenceId` 互相引用，**禁止写入绝对路径**（§11）。

### 2.2 逐文件规格

| 文件 | 写入者（唯一） | 格式 / 契约 | 可删？ | 大小上限 |
|---|---|---|---|---|
| `paper.pdf` | `LibraryService.import`（复制一次） | PDF 二进制；字节 sha256 必须等于 `meta.json#docId` | **否**（删除 = 取消导入） | ≤ 512 MiB（超出拒绝导入 `FR-STORE-019`） |
| `meta.json` | `LibraryService`（`MetaStore`） | `schemas/meta.schema.json`；UTF-8，2 空格缩进 + 末尾换行（便于 Git diff） | 否 | ≤ 64 KiB |
| `blocks.json` | `AnchorStore`（解析产物） | `schemas/doc-anchor-model.schema.json`；`JSON.stringify(model, replacer)` 无缩进（体积优先） | 是（重解析可重建；期间重排视图不可用，原文模式仍可用） | ≤ 64 MiB（超出 `FR-STORE-020`） |
| `notes.md` | `NoteService`（唯一写入者） | 纯 Markdown，UTF-8 无 BOM，LF；**不得**嵌入 HTML 注释状态块 | 否（用户内容） | 软上限 4 MiB，超限警告不阻断 |
| `annotations.jsonl` | `NoteService` | 见 §4，每行一条 JSON + `\n` | 否（用户内容） | 单行 ≤ 8 KiB；文件 > 64 MiB 时 `--check` 报 `FR-STORE-016` 并建议 `--compact` |
| `translation/<lang>.jsonl` | `TranslateService` | 见 §5 | 是（缓存语义，可重建） | 单行 ≤ 2 KiB；文件 ≤ 64 MiB（超出按 LRU 截断 + `warn`） |
| `patches/<ulid>.json` + `.fr-meta.json` | `PatchStore` / `LibraryService` | 见 §6；内部清单为 `{fileHashes:{[relPath]:sha256}, indexState:{docId,indexedAt,schemaVersion}}` | 补丁否（用户内容）；清单是（删后 `--verify-hashes` 退化为全量校验） | 补丁单文件 ≤ 1 MiB、单文档 ≤ 512 个；清单 ≤ 16 KiB |

> `00-conventions.md` §3 的"单文件 ≤ 400 行"针对**源码**；上述数据文件不受约束，但 `notes.md` 与 `annotations.jsonl` 必须流式读取（禁止整文件 `readFileSync`）。
> 每条用户内容文件都必须能在**不清空数据**的前提下被 `doctor` 修复；唯一允许"删除即丢信息"的是 `blocks.json` 与 `translation/*`（均可由 `paper.pdf` 重算）。

---

## 3. citekey 生成、冲突与重命名

### 3.1 生成算法（确定性纯函数）

```ts
// packages/core/src/storage/citekey.ts
export function makeCitekey(meta: Pick<Meta, 'authors' | 'year' | 'title'>, taken: ReadonlySet<string>): string
```

| 步 | 规则 |
|---|---|
| 1 | `family = meta.authors[0].family` 转小写；`authors` 为空 → `anon` |
| 2 | 取 `family` 中首个 ASCII 字母序列 `/[a-z]+/` 的 `match[0]`；无匹配 → `sha256(JSON.stringify(meta)).slice(0,6)` |
| 3 | `year = meta.year`；缺失 → `nd` |
| 4 | `word` = `title` 转小写、NFKD 去变音、剔除 `[^a-z0-9 ]` 后切词，丢弃停用词（常量 `CITEKEY_STOPWORDS`：`a an the of on in for and or to with from by at is are new study …` 共 32 词）后取**首个实词**；为空则省略 |
| 5 | 拼接 `${family}${year}${word}`，仅保留 `[a-z0-9-]`（其余字符丢弃）；截断到 **40** 字符（`MAX_CITEKEY_LEN`），截断后若以 `-` 结尾则去尾 |
| 6 | 结果为空（非拉丁标题且无作者）→ `doc-${docId.slice(0,8)}` |
| 7 | 冲突消解：`taken` 含 `k` → 依次试 `k-2`、`k-3`…（n 从 2 起），总长仍 ≤ 40（超长先截断基串再加后缀） |

示例：`Vaswani et al. 2017 "Attention Is All You Need"` → `vaswani2017attention`；`Zhang 2024 "A Study of the Effects of …"` → `zhang2024study`（`a`/`of`/`the` 属停用词）；无作者无年份的中文标题 → `doc-3f9a1c07`；已有 `vaswani2017attention` 时再导入同作者 2017 年论文 → `vaswani2017attention-2`。

**不变量**：**INV-S1** `library/` 同级目录名唯一，`document.citekey` 唯一索引（§7）；**INV-S2** `citekey` 一旦确定不得因元数据编辑而自动变化（只允许用户显式重命名）；**INV-S3** 旧 `citekey` 写入 `citekey_alias` 表，保证旧链接与 `notes.md` 中 `[[citekey]]` 可解析。

### 3.2 用户重命名（改名 = 移动目录 + 更新索引）

| 步 | 动作 | 崩溃后收敛（`doctor --check`） |
|---|---|---|
| 1 | 校验新 citekey（§3.1 规则 + 保留名 + 无同名目录），否则 `FR-STORE-014` | 无变化 |
| 2 | 取该 citekey 写锁（§10.2） | 锁自动过期 |
| 3 | `rename(L/<old>, L/<new>.tmp-<ulid>)` | `<new>.tmp-*` 残留且 `<old>` 不存在 → 动作 `R4` 回滚为 `<old>` |
| 4 | `rename(L/<new>.tmp-<ulid>, L/<new>)` | 同上 |
| 5 | 单事务：`UPDATE document SET citekey=?, updated_at=? WHERE doc_id=?` + `INSERT INTO citekey_alias` | 目录已改、索引仍旧 → 动作 `R1` 按 `doc_id` 重灌 |
| 6 | 原子改写 `meta.json#citekey`（§1.1） | 同 5；追 `op_log(op='rename')` 只丢审计 |

**新增错误码**（格式 `FR-<AREA>-<3位>`；下表左列为**新增**，右列为**复用** `11-error-handling.md` 中已有语义相同的码）

| 新增码 | 含义 | 复用码（已存在，直接引用） | 含义 |
|---|---|---|---|
| `FR-STORE-012` | 文件写入/fsync/rename 失败（`ENOSPC`/`EACCES` 分别走 `-001`/`-002`） | `FR-STORE-004` | SQLite 损坏（`PRAGMA integrity_check` 非 `ok`） |
| `FR-STORE-013` | 序列化结果不满足对应 JSON Schema（不落盘） | `FR-STORE-005` | 索引与文件不一致（可修复，不阻断阅读） |
| `FR-STORE-014` | citekey 非法或冲突且无法自动消解 | `FR-STORE-006` | 迁移失败，已从备份回滚 |
| `FR-STORE-015` | `paper.pdf` 字节 sha256 ≠ `meta.json#docId` | | |
| `FR-STORE-016` | `annotations.jsonl` 存在不可解析行 | | |
| `FR-STORE-017` | 标注引用的 `sentenceId`/`blockId` 不存在 | | |
| `FR-STORE-018` | 补丁 `docId`/`schemaVersion` 不匹配当前 `blocks.json` | | |
| `FR-STORE-019` | 导入的 PDF 超过 512 MiB | | |
| `FR-STORE-020` | 产物文件超过大小上限 | | |
| `FR-STORE-021` | 数据库 `user_version` 高于应用支持版本（需升级应用） | | |
| `FR-STORE-022` | 存在悬挂临时文件（`--check` 只报，`--clean` 才删） | | |

> `FR-STORE-007`（缓存写入失败）与 `FR-STORE-008`（配置非法）由其他模块触发，本文不重复定义；`FR-STORE-001`/`-002`/`-003`（磁盘空间/权限/路径过长）是 `-012` 的三个特例，`up()`/`atomicWriteFile()` 必须先按 `errno` 分流。

**登记信息**（供 `11-error-handling.md` 直接抄录；i18n 文案同时写入 `zh-CN.json` / `en.json`）

| 码 | 级别 | 重试 | 用户文案（i18n key → zh-CN） | 建议动作 |
|---|---|---|---|---|
| `FR-STORE-012` | fatal | U | `errors.FR-STORE-012`「保存失败，文件未被修改」 | 重试 / 检查磁盘与权限 |
| `FR-STORE-013` | error | N | `errors.FR-STORE-013`「数据结构校验未通过，已阻止写入」 | 导出日志 / 重解析 |
| `FR-STORE-014` | error | U | `errors.FR-STORE-014`「引用键不可用，请换一个」 | 修改引用键 |
| `FR-STORE-015` | error | U | `errors.FR-STORE-015`「PDF 文件与记录不一致」 | 重新导入 / 忽略并重新解析 |
| `FR-STORE-016` | warn | N | `errors.FR-STORE-016`「部分标注无法读取，已跳过」 | 运行 `doctor --compact` |
| `FR-STORE-017` | warn | U | `errors.FR-STORE-017`「该标注的原文位置已失效」 | 重新解析 / 保留笔记 |
| `FR-STORE-018` | warn | N | `errors.FR-STORE-018`「排版修正与当前版本不匹配，已跳过」 | 重新纠错 / 重解析 |
| `FR-STORE-019` | error | N | `errors.FR-STORE-019`「PDF 过大，暂不支持导入」 | 选择更小的文件 |
| `FR-STORE-020` | warn | N | `errors.FR-STORE-020`「生成的数据超过体积上限，已截断或跳过」 | 重新解析（必要时换引擎） |
| `FR-STORE-021` | fatal | N | `errors.FR-STORE-021`「数据版本高于当前应用，请升级 FreeRead」 | 升级应用 |
| `FR-STORE-022` | warn | N | `errors.FR-STORE-022`「发现上次未完成的临时文件」 | 运行 `doctor --clean` |

---

## 4. `annotations.jsonl` 规范

| # | 写入规则（REQUIRED） |
|---|---|
| A1 | **单行一条 JSON**，对象完整、无数组包裹、`\n` 结尾（末行也必须有）；禁止 pretty-print |
| A2 | **只允许追加**（`flags:'a'`）：禁止重写文件、禁止原地修改既有行 |
| A3 | 修改 = 追加**同 `id` 的新版本**（携带 `updatedAt`）；读取时**按文件出现顺序取最后一条**胜出 |
| A4 | 删除 = 追加 `deleted:true` **墓碑**；**禁止物理删除行**；仅 `freeread doctor --compact` 允许重写文件并丢弃墓碑（§9.1） |
| A5 | 字段以 `schemas/annotation.schema.json` 为唯一契约；不得出现未声明字段（`additionalProperties:false`） |
| A6 | `anchor` **只允许** `page` / `blockId` / `sentenceId` / `rects` / `lines`；**禁止**文本偏移、DOM 路径、像素坐标、缩放后坐标 |
| A7 | `rects` 单位为 **PDF point**、页面左上原点（`03-anchor-model.md` §3）；`scale` 由 UI 渲染时套用，**不入库** |
| A8 | 写入前逐条校验；失败 → `FR-STORE-013`，该行不落盘并报错（禁止静默丢弃） |
| A9 | 同一 `citekey` 的追加写必须串行（§10.2），保证每行 ≤ 8 KiB 且单次追加原子（POSIX `O_APPEND`；Windows 由进程内互斥 + 单写者锁保证） |

**真实示例（三行，逐字节合法的文件内容）**

```jsonl
{"schemaVersion":1,"id":"an_01H8ZQ7K3M9F2T4V6X8A0B1C2D","docId":"3f9a1c07e5b24d8a9c6f0b1d2e3a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c","kind":"highlight","anchor":{"page":3,"blockId":"b_3_7","sentenceId":"s_b_3_7_2","rects":[{"x":72.1,"y":301.4,"w":210.3,"h":11.8},{"x":72.1,"y":315.2,"w":88.6,"h":11.8}],"lines":[{"lineId":15,"page":3,"begin":0,"len":3}]},"color":"yellow","quote":"we propose a dual-view anchor model","tags":["method"],"createdAt":"2026-10-03T00:31:12.480Z","deviceId":"dev_01H8ZQ7K3M9F2T4V6X8A0B1C2D"}
{"schemaVersion":1,"id":"an_01H8ZQ7K3M9F2T4V6X8A0B1C2E","docId":"3f9a1c07e5b24d8a9c6f0b1d2e3a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c","kind":"note","anchor":{"page":3,"blockId":"b_3_7","sentenceId":"s_b_3_7_2","rects":[],"lines":[]},"note":"这里的 IoU 阈值与 03 章 §7 的 0.98 指标对应，别混淆。","createdAt":"2026-10-03T00:33:41.002Z","updatedAt":"2026-10-03T00:35:02.117Z","deviceId":"dev_01H8ZQ7K3M9F2T4V6X8A0B1C2D"}
{"schemaVersion":1,"id":"an_01H8ZQ7K3M9F2T4V6X8A0B1C2F","docId":"3f9a1c07e5b24d8a9c6f0b1d2e3a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c","kind":"bookmark","anchor":{"page":12,"blockId":"b_12_1","sentenceId":"s_b_12_1_1","rects":[],"lines":[]},"note":"实验部分起点","createdAt":"2026-10-03T01:02:00.000Z","deviceId":"dev_01H8ZQ7K3M9F2T4V6X8A0B1C2D"}
```

> `id` = `an_` + ULID（`README.md` §3）；`docId` 必须是 64 位小写 hex 且与 `paper.pdf` 字节一致。

**读取与合并**：① 流式逐行 `JSON.parse`，失败行跳过并计数（`--check` 报 `FR-STORE-016`，`--rebuild` 记 `warn` 后继续）；② 按 `id` 归并取最后一条，`deleted:true` 从视图剔除但保留用于同步与冲突检测；③ `anchor.sentenceId` 必须存在于 `blocks.json#sentences`，否则报 `FR-STORE-017`（**不删除**标注，标记"待重解析"）；④ 归并后的最终状态写入 SQLite `annotation` 表（§7）。

---

## 5. `translation/<lang>.jsonl` 规范

```jsonc
{
  "schemaVersion": 1,
  "unit": "sentence",              // "paragraph" | "sentence"（同 08-translation.md 的 TranslationUnit）
  "unitId": "s_b_3_7_2",           // paragraphId（pa_x_y）或 sentenceId
  "sourceHash": "9f2c…(64 hex)",   // sha256(规范化源文本)
  "target": "我们提出一种双视图锚点模型。",
  "provider": "ollama:qwen2.5:7b", // "<providerName>:<model>"
  "createdAt": "2026-10-03T00:40:00.000Z"
}
```

| # | 规则 |
|---|---|
| T1 | 追加写；同一 `unitId` 允许多行，读取时取**文件内最后一条**且 `sourceHash` 必须匹配 |
| T2 | `sourceHash = sha256(s)`，`s` 的规范化 = **Unicode NFC → 去首尾空白 → 连续空白（含 `\n` `\r` `\t` U+3000）折叠为单个 `0x20`** |
| T3 | 源文本变化 → `sourceHash` 不匹配 → 该行**立即失效**（按 miss 处理，重译后追加新行）；旧行不删（`--compact` 清理） |
| T4 | 缓存命中判定：`unitId` 相同 **且** `sourceHash` 相同 **且** `provider` 相同 |
| T5 | 文件可整体删除（缓存语义），删除后按需重译；`target` 是唯一可能较长字段（≤ 2 KiB/行），禁止写入任何密钥或原文以外的用户隐私内容 |
| T6 | 按语言隔离；`targetLang` 必须匹配 `^[a-z]{2}(-[A-Z]{2})?$`（如 `zh-CN`）；Provider 调度见 `08-translation.md` |

---

## 6. `patches/` 纠错补丁规范

```jsonc
{
  "schemaVersion": 1,
  "docId": "3f9a1c07…(64 hex)",   // 必须等于当前 blocks.json#docId
  "rulesRevision": 7,              // PARSER_RULES_REVISION（03-anchor-model.md §8）
  "createdAt": "2026-10-03T02:10:00.000Z",
  "ops": [
    { "op": "retype", "blockId": "b_3_7", "type": "abstract", "score": 1 },
    { "op": "move",   "blockId": "b_3_9", "afterBlockId": "b_3_5" },
    { "op": "merge",  "blockId": "b_3_7", "withBlockIds": ["b_3_8"], "type": "text" },
    { "op": "split",  "blockId": "b_3_7", "atLineId": 15, "into": ["text", "text"] },
    { "op": "delete", "blockId": "b_3_12" }
  ]
}
```

| op | 必填字段 | 语义 |
|---|---|---|
| `retype` | `blockId`, `type`（`BlockType` 之一） | 改写块类型；`score` 可选，设置后覆盖原值（默认 `1` = 人工确认） |
| `move` | `blockId`, `afterBlockId`（`null` = 移到最前） | 只调整阅读顺序；重排后按 `order` 重新编号，**不改变 `blockId`** |
| `merge` | `blockId`, `withBlockIds` | 把后者的文本/行并入前者；被并入块从渲染模型移除 |
| `split` | `blockId`, `atLineId` | 在指定 `lineId` **之前**切分；`into` 给出各段 `type`（默认沿用原 `type`） |
| `delete` | `blockId` | 从渲染模型移除该块（不修改磁盘上的 `blocks.json`） |

| # | 应用规则 |
|---|---|
| P1 | **补丁永不修改 `blocks.json`**；渲染时叠加 `renderModel = applyPatches(blocks.json, patches)`（`packages/core/src/patch/apply.ts`，纯函数、无 IO） |
| P2 | 应用顺序：文件名 ULID **字典序升序**（ULID 单调递增 = 创建时间序）；同文件内按 `ops` 数组顺序 |
| P3 | 可重放性：`applyPatches` 对同一 `(blocks, patches)` 必须确定性、幂等，且不产生随机 ID |
| P4 | 陈旧补丁：`ops[i].blockId` 不存在 → 跳过该 op、`staleOps++`、记 `warn: patch.stale`，**其余 op 继续**（不得整包丢弃） |
| P5 | `docId` 不匹配 → 整文件忽略 + `FR-STORE-018`；`schemaVersion` 高于应用支持 → 忽略 + `FR-STORE-018` |
| P6 | `rulesRevision` 不同 → 仍应用，UI 提示"补丁基于旧规则"（i18n `reader.banner.patchStale`）；`staleOps / totalOps ≥ 0.30` → 建议重新解析或丢弃补丁 |
| P7 | 应用后模型必须再通过 `03-anchor-model.md` INV-1..10 校验（重点 `Rect` 越界与 `order` 单调）；失败 → 放弃补丁、回退原始模型 + `warn: patch.rejected` |
| P8 | 补丁是**用户内容**，不可删除；导出与同步必须包含 `patches/` |
---

## 7. SQLite 完整 DDL（`schema.sql`）

位置 `%APPDATA%/FreeRead/index.sqlite`（Linux `~/.config/FreeRead/index.sqlite`）。驱动 `better-sqlite3`（MIT）。以下脚本**可直接执行**，且必须与 `packages/core/src/storage/schema.sql` 逐字节一致（`pnpm gen:check` 校验）。

```sql
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
```

### 7.1 表 ← 文件 重建映射

| 表 | 唯一来源 | 重建动作 |
|---|---|---|
| `schema_migrations` | 应用代码（非文件真源） | 执行 `migrations/` 后写入；不参与重建 |
| `document` | `meta.json` + 目录名 + `blocks.json` | 扫描 `library/*/`：`citekey = dirname`、`doc_id = meta.docId`、`title/authors/year/venue/doi/arxivId/pageCount/language/quality/source` 取 `meta`；`parser_engine/parser_version` 取 `blocks.json#engine`；`rules_revision` 取 `blocks.json#meta.parserRulesRevision`；`read_state/read_progress/last_*` 为**索引专属**（重建保留旧值，见 §11 PR5） |
| `document_tag` / `document_collection` | `meta.tags[]` / `meta.collections[]` | 逐条展开插入 |
| `citekey_alias` | `<libraryPath>/.aliases.jsonl`（重命名时追加 `{old,new,docId,changedAt}`） | 逐行插入 |
| `annotation` | `annotations.jsonl` | 流式读取 → 按 `id` 归并取最后一条 → `json` 存行原文、`deleted` 取墓碑 |
| `translation_cache` | `translation/<lang>.jsonl` | 逐行读取 → `cache_key` 由行内字段重算 → 按 `(doc_id, lang, cache_key)` 取最后一条 |
| `op_log` | `<libraryPath>/.oplog.jsonl`（与表同构） | 逐行插入（`client_event_id` 冲突忽略） |
| `doc_fts` | `blocks.json`（`sentences[].text` 拼接为 `body`） | 见 §7.2 / §7.3 |

> `--rebuild` 必须先备份现有 `index.sqlite`（§8.4），再 `DROP` 除 `schema_migrations` 外的全部表并重放。

### 7.2 填充时机

① 导入 `LibraryService.import`：写 `meta.json` → 单事务插入 `document` + `document_tag`，**不填 `doc_fts`**（尚无 `blocks.json`）。
② 解析完成 `AnchorStore.commit`：写 `blocks.json` → 单事务更新 `document` 解析字段 + 插入 `doc_fts`（**唯一常规填充点**）。
③ 重新解析（引擎 / rules 变更）：先按 contentless 协议删除旧行再插入，禁止重复行。
④ 元数据编辑（标题/摘要变化）：更新 `document` + 重写该行 FTS 记录。
⑤ `doctor --rebuild`：全量重建（§7.1）。

```ts
const rowid = parseInt(docId.slice(0, 12), 16);   // 48-bit rowid，稳定且唯一
const write = "INSERT INTO doc_fts(rowid,title,abstract,body) VALUES (?,?,?,?)";
const del = "INSERT INTO doc_fts(doc_fts,rowid,title,abstract,body) VALUES ('delete',?,?,?,?)";
db.prepare(write).run(rowid, meta.title, meta.abstract ?? '', segmentForFts(body, locale));
db.prepare(del).run(rowid, meta.title, meta.abstract ?? '', segmentForFts(body, locale));
```

### 7.3 中文分词取舍（决定 `body` 的写入形态）

| 方案 | 做法与优缺点 | 结论 |
|---|---|---|
| A. `unicode61` 原样写入 | 直接把中文串写入 `body`。零成本，但 `unicode61` 不切分 CJK，整段中文成为**一个 token**，中文检索基本失效 | **禁止** |
| B. `unicode61` + 应用层分词 | 写入前用 `Intl.Segmenter(locale, {granularity:'word'})` 切词，**以空格连接**写入 `body`（`title`/`abstract` 同法）。零新依赖（Node 内置 ICU）、体积最小、中英同库同查询语法；`snippet()` 返回切词后文本（UI 高亮用原始 `sentences[].text`，不依赖 snippet）。代价：查询串必须走**同一分词函数**（已封装 `segmentForFts()`，禁止查询侧另写一套），且不支持任意子串匹配 | **默认方案（V1）** |
| C. `tokenize='trigram'` | 不切词，靠三字组。支持子串/模糊匹配、中文无需分词；但索引约 3–5× 体积、2 字查询退化、英文噪声高 | 仅作**可选第二索引** `doc_fts_trigram`（设置项 `search.trigram`，默认 `false`），V1 不启用 |

**REQUIRED**：`segmentForFts(text: string, locale: string): string` 定义在 `packages/core/src/search/segment.ts`；索引写入与查询构造**必须**调用同一函数（用例 `T-STORE-FTS-SYMMETRY` 断言 `segmentForFts(q)` 能命中索引）。

---

## 8. 迁移策略

### 8.1 版本表与函数签名

```ts
// packages/core/src/storage/migrate.ts
export interface Migration {
  readonly version: number;                     // 从 1 起连续递增，等于目标 user_version
  readonly name: string;                        // kebab-case，如 'add-document-language'
  readonly checksum: string;                    // sha256(up.toString())，构建期注入
  readonly up: (from: number, db: Database) => void;
}
export function migrate(from: number, db: Database): number;   // 输入当前 user_version，返回迁后版本
```

启动时读 `PRAGMA user_version`：`v > APP_SCHEMA_VERSION` → 停止并抛 `FR-STORE-021`（**禁止**自动降级、禁止隐式丢列）；`v < APP_SCHEMA_VERSION` → 按 `version` 升序执行，**每个迁移一个事务**，成功后 `INSERT INTO schema_migrations` + `PRAGMA user_version = n`；已存在行的 `checksum` 不匹配 → 迁移文件被改动，抛 `FR-STORE-005` 要求人工处理（禁止静默继续）。

### 8.2 幂等要求（REQUIRED）

每个 `up()` 必须可重复执行且结果相同（可能在上次提交后崩溃）：建表/索引用 `IF NOT EXISTS`；加列先查 `PRAGMA table_info(<t>)`，存在则跳过；数据回填用 `UPDATE … WHERE <目标列> IS NULL`（禁止无条件 `UPDATE`）；删列优先 `ALTER TABLE … DROP COLUMN`（SQLite ≥ 3.35），否则"建新表 → `INSERT INTO new SELECT` → `DROP` → `RENAME`"。单测 `T-STORE-MIGRATE-IDEMPOTENT`：对空库与"已迁到 n 的库"各跑一次 `up()`，断言规范化转储相等。

### 8.3 失败与回滚

1. 迁移前 `PRAGMA wal_checkpoint(TRUNCATE)` 并关闭连接。
2. 复制 `index.sqlite` 为备份（命名见 §8.4），校验备份可打开且 `PRAGMA integrity_check = 'ok'`。
3. 任一迁移失败 → 抛 `FR-STORE-006`，关闭连接，**用备份覆盖** `index.sqlite`（并删除 `-wal`/`-shm`），记 `error` 日志（`from_version`、`migration_name`、`sqlite_error_code`）。
4. 回滚后以**只读模式**启动：可打开文档、可导出，**禁止写**；UI 横幅 `app.banner.storageReadonly`。最终恢复路径为 `freeread doctor --rebuild`（从文件真源重建，不依赖迁移成功）。

### 8.4 备份命名与保留策略

```
%APPDATA%/FreeRead/backups/index-YYYYMMDDTHHmmssZ-v<fromVersion>.sqlite   # 例：index-20261003T003000Z-v3.sqlite
```

保留最近 **5** 个备份 ∪ 最近 **30 天**内的备份（取并集后删除其余，按文件名时间戳排序）；备份目录总量 ≤ 1 GiB，超出按最旧优先删除；设置页提供"打开备份目录"与"从备份恢复"（二次确认）；**禁止**把备份写入 `library/`（会污染真源与同步盘）。

### 8.5 `blocks.json` 的版本迁移

`blocks.json#schemaVersion` 迁移**不属于** SQLite 迁移体系，遵循 `03-anchor-model.md` §8：字段语义变更/删除/类型改变才 bump，并提供 `migrateAnchorModel(vN→vN+1)`。读取时 `schemaVersion < CURRENT` → **内存中迁移** → 校验通过后原子写回（§1.1）并 bump `document.updated_at`；写回失败则仅内存使用（本次会话可用，下次再试）。`> CURRENT` → 视为未知版本，抛 `FR-STORE-013`，UI 提示"请升级 FreeRead"，**禁止**猜测字段。引擎升级（`engine.version` 变化）**不 bump** schemaVersion，但缓存键失效（`03-anchor-model.md` §8）→ 触发重解析，走 §7.2 的重解析填充路径。

---

## 9. `freeread doctor` 工具

CLI 位于 `apps/cli`（包名 `@freeread/cli`，bin `freeread`）；所有子命令支持 `--library <path>` 与 `--json`（机器可读输出，供 E2E 断言）。

### 9.1 子命令

| 子命令 | 检测内容 | 修复动作 | 退出码 |
|---|---|---|---|
| `doctor --check` | ① `meta.json` 缺失/不合法；② `docId` ≠ `paper.pdf` sha256；③ 索引行缺失或 `citekey` 不一致；④ `annotations.jsonl` 不可解析行；⑤ 标注引用的 `sentenceId` 不在 `blocks.json`；⑥ 有目录无 `meta.json`（孤儿）；⑦ 悬挂临时文件；⑧ `patches/*.json` 的 `docId` 不匹配 | **只报不改**；加 `--fix-safe` 仅执行幂等动作 `R1`/`R4` | `0` 无问题 / `1` 有警告 / `2` 有需修复项 / `64` 参数错误 |
| `doctor --rebuild` | 索引与真源的全量差异 | 备份现有索引（§8.4）→ 删除并重建 `document`/`annotation`/`translation_cache`/`op_log`/`doc_fts`（§7.1）→ `PRAGMA integrity_check` + 行数校验 | `0` 成功 / `2` 部分文档重建失败（逐个报告） / `3` 无法打开或写入数据库 |
| `doctor --compact` | 标注墓碑与历史版本；译文失效行 | 原子重写：标注保留每 `id` 最后一条且丢弃 `deleted:true`；译文丢弃 `sourceHash` 不匹配行；重写前备份 `<file>.bak-<ulid>`（保留最近 3 个） | `0` 成功 / `2` 有文件无法解析（跳过并报告） / `3` 写入失败 |
| `doctor --orphans` | ① 无 `meta.json` 的目录；② 索引 `doc_id` 的目录不存在；③ `blockId`/`sentenceId` 悬空的标注；④ `patches/` 中 `docId` 不属于该目录的补丁 | 默认**只列表**；`--prune` 才把孤儿目录移到 `<libraryPath>/.trash/<citekey>-<ulid>/`（不直接删除） | `0` 无孤儿 / `1` 有孤儿但未 `--prune` / `2` `--prune` 已完成 |
| `doctor --verify-hashes` | `paper.pdf` sha256 vs `meta.json#docId`；`.fr-meta.json` 记录的其余文件哈希 vs 实际；`blocks.json` schema 校验 | **不改写 PDF**；不一致 → 报告并将该文档标记 `quality='mixed'` 交用户决定；`blocks.json` 校验失败 → 建议重解析 | `0` 全部一致 / `2` 存在不一致 / `3` 读取失败（权限或 IO） |

**修复动作 ID**（用于 `--json` 输出与测试断言，全部幂等）：`R1` 按 `docId` 重灌索引行；`R2` 孤儿目录 → `.trash/`；`R3` 删除过期悬挂临时文件（§10.3）；`R4` `*.tmp-*` 回滚为原名；`R5` 迁移 `blocks.json` 到当前 `schemaVersion` 并写回；`R6` 重写该文档的 `doc_fts` 行。

### 9.2 退出码约定（全 CLI 统一）

| 码 | 含义 |
|---|---|
| `0` | 成功，无需处理 |
| `1` | 成功，但有警告（数据可用） |
| `2` | 成功，但发现并/或修复了问题（需用户知晓） |
| `3` | 失败：无法完成（IO/DB/权限），未产生部分修改 |
| `64` | 用法错误（未知子命令、参数非法） |

---

## 10. 并发与锁

### 10.1 单实例锁

| 项 | 规定 |
|---|---|
| 文件 | `%APPDATA%/FreeRead/app.lock` |
| 内容 | `{pid, startedAt, host, version}`（JSON 单行） |
| 获取 | 启动时 `open(O_CREAT\|O_EXCL)`；成功即持有，退出时删除（`process.on('exit')`） |
| 已存在 | 读 `pid`：进程存活（`process.kill(pid, 0)` 成功）→ 聚焦已有窗口（`second-instance`）后退出；进程不存在 → 视为过期锁，删除并重新获取 |
| 兜底 | `startedAt` 超过 **24 h** 一律视为过期（防 pid 复用），覆盖前记 `warn: lock.stale` |
| 并存 | 允许**只读 CLI**（`doctor --check`、`--verify-hashes`）与主实例并存；写类子命令必须等锁 |

### 10.2 写互斥（同一 citekey 串行化）

```ts
// packages/core/src/storage/keyed-mutex.ts
export function withCitekeyLock<T>(citekey: string, fn: () => Promise<T>): Promise<T>;
```

| 项 | 规定 |
|---|---|
| 粒度 | 以 `<libraryPath>/<citekey>` 的**规范绝对路径**（`realpath` 后）为键 |
| 作用域 | 进程内 Promise 链（主进程单写者）；CLI 与桌面端之间由 `library/.lock`（`proper-lockfile`，MIT）互斥 |
| 等待 | 上限 **10 s**（`LOCK_WAIT_MS`）；超时抛 `FR-STORE-012` 并提示"另一进程正在写入"，退出码 `3` |
| 覆盖 | 该 citekey 下**全部**写操作：`meta.json`、`blocks.json`、`notes.md`、`annotations.jsonl`、`translation/*`、`patches/*` 及索引行更新 |
| 禁止 | 禁止跨 citekey 持锁调用另一个 citekey 的写路径（死锁）；批量操作按 `citekey` 字典序逐个加锁 |
| 事务 | SQLite 写事务一律 `BEGIN IMMEDIATE`（避免锁升级死锁）；单事务 ≤ 200 ms；`busy_timeout=5000` |

### 10.3 崩溃后的悬挂文件清理

**命名**：`<target>.<pid>.<ulid>.tmp`（如 `meta.json.4821.01H8ZQ….tmp`）；目录重命名用 `<citekey>.tmp-<ulid>`。**位置**：必须与目标同目录（保证同卷 rename 原子）。
**判定"悬挂"**：名称匹配 `\.tmp$` 或 `\.tmp-[0-9A-HJKMNP-TV-Z]{26}$`，且 `mtime` 早于**进程启动时刻**或超过 **24 h**（`TMPFILE_STALE_HOURS`）。
**处理**：`--check` 只报告（`FR-STORE-022`，候选动作 `R3`）；`doctor --clean` / `--fix-safe` 删除满足判定者，**不删** 24 h 内且进程仍存活的文件；主进程启动时对当前 `libraryPath` 执行一次同规则清理（仅删 24 h 以上），记 `info: storage.tmp.cleaned {count}`。
**禁止**："删除所有 `*.tmp`"的粗暴规则（可能删掉正在写入的文件）。

---

## 11. 隐私与可迁移性

| # | 规则 |
|---|---|
| PR1 | 本地绝对路径**只允许**出现在 `config.json`（`libraryPath`/`cachePath`）与 `logs/`；**禁止**写入 `meta.json`、`annotations.jsonl`、`translation/*.jsonl`、`patches/*.json`、`blocks.json`、`op_log`、导出文件 |
| PR2 | `meta.source.url` 只保存**远程** URL（OA 来源，见 `09-fetch-compliance.md`）；本地导入时 `source.kind='local-file'` 且**省略** `url`（不写 `file://` 路径） |
| PR3 | 导出/分享（Markdown / JSON / 标注 CSV）必须过 `sanitizeExport()`：剥离 `source.url` 的本地段、剔除 `deviceId`，可选把 `docId` 替换为 `sha256(docId).slice(0,8)`；默认导出即已匿名化。日志脱敏遵循 `00-conventions.md` §5（白名单制）：不记笔记/译文全文、密钥与路径中的用户名段，只记长度与 hash |
| PR4 | 密钥/令牌（OpenAI 兼容 API key、WebDAV 密码）**必须**存 OS Keychain（Windows Credential Manager / macOS Keychain / libsecret），服务名 `dev.freeread.app`、账号 `provider:<name>`；`config.json` 只允许 `baseUrl`、`username`、`model` 等非敏感字段（`schemas/app-config.schema.json` 以 `additionalProperties:false` 强制） |
| PR5 | 迁移 = 拷贝：`library/` 整体复制后指向新 `libraryPath` 并 `doctor --rebuild` 即可用。**无隐藏状态**；唯一例外是 `document.read_state/read_progress/last_*`（阅读进度）属索引专属，V1 明确接受其丢失（重读成本 ≤ 1 次翻页）。云同步由用户自选，应用只做文件级冲突检测（`mtime + sha256`）与提示，不上传任何数据（ADR-09） |

---

## 12. 性能预算与常量

新增存储阈值必须进 `packages/core/src/budgets.ts` 并在 `10-testing.md` 登记指标卡（`00-conventions.md` §9）：

```ts
export const STORAGE_LIMITS = {
  MAX_PDF_BYTES: 512 * 1024 * 1024,        // FR-STORE-019
  MAX_META_BYTES: 64 * 1024,
  MAX_BLOCKS_BYTES: 64 * 1024 * 1024,      // FR-STORE-020
  MAX_ANNOTATION_LINE_BYTES: 8 * 1024,
  MAX_ANNOTATIONS_BYTES: 64 * 1024 * 1024,
  MAX_TRANSLATION_LINE_BYTES: 2 * 1024,
  MAX_TRANSLATION_BYTES: 64 * 1024 * 1024,
  MAX_PATCHES_PER_DOC: 512,
  MAX_CITEKEY_LEN: 40,
  REBUILD_DOCS_PER_SECOND_MIN: 20,         // --rebuild 吞吐下限（含 FTS 重建）
  CHECK_MS_PER_DOC_MAX: 50,                // --check 单文档上限
  TMPFILE_STALE_HOURS: 24,
  LOCK_WAIT_MS: 10_000,
} as const;
```

---

## 变更记录

| 版本 | 日期 | 变更 | schemaVersion |
|---|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：真源原则与原子写协议（临时文件 + rename + fsync → 索引）、知识库布局与逐文件规格、citekey 生成/冲突/重命名原子步骤、`annotations.jsonl`（追加 + 墓碑 + 三示例）、译文缓存 `sourceHash` 失效规则、纠错补丁可重放规范、SQLite 完整 DDL 与表←文件重建映射、FTS5 中文分词取舍（`unicode61` + 应用层分词）、迁移/备份/回滚策略、`doctor` 五子命令与退出码、单实例锁/写互斥/悬挂文件清理、隐私与整体拷贝迁移；错误码与 `11-error-handling.md` 对齐（新增 `FR-STORE-012..022`，复用 `-004/-005/-006`） | 1（`meta` / `annotation` / `app-config` / `blocks` 均为 1） |
| v1.0-r2 | 2026-10-03 | **跨规范冲突裁决（Lead）**：`translation_cache` 主键由 `(doc_id, lang, unit_id)` 改为 **`(doc_id, lang, cache_key)`**，并新增 `provider_id`/`model_id`/`glossary_hash`/`cache_key`/`last_used_at`/`hits`/`bytes` 列。原因：`08-translation.md` §6.1 要求缓存键包含 provider + model + 术语表指纹，原主键会导致「切换 Provider / 修改术语表后无法共存」。同步修正 §1 规范化转储的排序键与 §7.2 重建映射。 | 1（不变；仅索引表结构变化，属可重建索引） |
