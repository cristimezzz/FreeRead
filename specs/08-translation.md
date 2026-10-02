# 08 · 翻译规范（Translation）

> 状态：**冻结**。定义 FreeRead 的 `TranslatorProvider` 抽象、批处理、提示词、术语表、缓存、划词与质量门禁。
> 上游依据：[`plan §2 ADR-10`](../plan/FreeRead-技术方案与里程碑.md)、[`plan §5 M4`](../plan/FreeRead-技术方案与里程碑.md)、[`report §5.5`](../report/Scholaread-调研报告.md)（反面对照：云端配额、按字数计费、译文模式禁高亮）。
> 术语以 [`README.md §3`](./README.md) 为准；**本包禁止直接发起网络请求**，一切出站经 `NetGuard`（[`09-fetch-compliance.md`](./09-fetch-compliance.md) §2），违反即 F2。
> 责任包：`packages/translate`（依赖 `packages/core` + `NetGuard`，**不得**依赖 `ui`/`react`/`electron`）。

## 1. 目标与边界

| 项 | 规定 |
|---|---|
| 翻译单元 | 最小单元 = `Sentence`（[`03-anchor-model.md`](./03-anchor-model.md) §5）；批 = 同 `Paragraph` 内连续 `Sentence` 的累积 |
| 离线可用 | 无网络/无模型/无 Key 时**必须**仍可用（`none` Provider 划词词典），不得出现空白面板 |
| 上传策略 | 仅 `kind='remote'` 可能把文本发往第三方；UI 首次启用须明确提示目标 host |
| 不做 | ❌ 内置免费翻译 API 池（ADR-10 被否：不稳定 + 违 ToS）；❌ 云端配额/账号；❌ 任何付费墙内容（`09` 红线） |
| 真源 | 译文落文件式知识库（`05-storage.md`），SQLite 仅作索引 |

## 2. Provider 抽象（权威接口）

```ts
// packages/translate/src/provider.ts
import type { GlossaryTerm } from '@freeread/core';

export type TranslationUnitKind = 'paragraph' | 'sentence' | 'selection' | 'dictionary';
/** docTitle = 论文标题（消歧）；field = 学科领域；surroundingText = 同段前后各 ≤ 200 字符（不计入批） */
export interface TranslateContext { docTitle?: string; field?: string; surroundingText?: string }
export interface TranslateRequest {
  texts: string[];            // 顺序即输出顺序；每元素 = 一个 TranslationUnit 的文本
  from?: string;              // BCP-47；缺省 = 自动检测
  to: string;                 // BCP-47，必填，如 'zh-CN'
  glossary?: GlossaryTerm[];  // 已按 §5.1 归一化
  context?: TranslateContext;
}
export interface TranslateResult {
  texts: string[];                        // length 必须 === 入参 texts.length，顺序一致
  providerId: string; modelId: string;    // modelId 参与缓存键
  from: string; to: string;
  usage?: { inputChars: number; outputChars: number };   // 只记长度，禁止记全文
  cached: boolean;                        // true = 完全命中缓存，未发出请求
}
export type TranslatorCapability = 'glossary' | 'json-batch' | 'stream' | 'offline' | 'context-window';
export interface TranslatorProvider {
  readonly id: string;        // 'ollama' | 'openai-compatible' | 'none' | '<plugin-id>'
  readonly kind: 'local' | 'remote';
  readonly capabilities: readonly TranslatorCapability[];
  /** 纯函数：无副作用、无缓存读写（缓存由 TranslationService 负责） */
  translate(req: TranslateRequest, signal: AbortSignal): Promise<string[]>;
  health(): Promise<{ ok: boolean; model?: string; detail?: string }>;
}
```

**错误约定**：Provider 不得返回部分结果；任何失败抛 `AppError`，码段 `FR-TRANS-xxx`。语义以 [`11-error-handling.md`](./11-error-handling.md) §3 为权威（本表与其逐条一致，`FR-TRANS-011..017` 为本文新增、需同 PR 登记）：

| 码 | 含义 | 本规范触发条件 | 可重试（11 §4） |
|---|---|---|---|
| `FR-TRANS-001` | Provider 未配置 / 无可用 Provider | `order` 全部 `health().ok === false`，或无 API Key | 否（引导配置） |
| `FR-TRANS-002` | 鉴权失败 | HTTP 401/403；Key 缺失或失效 | 用户确认后重试 |
| `FR-TRANS-003` | 限流 | HTTP 429 / 来源方 `Retry-After` | 是（退避 ≤ 2 次，429 读 `Retry-After`） |
| `FR-TRANS-004` | 请求超时 | 单批 > 30 s（`TRANSLATE_TIMEOUT_MS`） | 是（退避 ≤ 2 次） |
| `FR-TRANS-005` | 连接中断 | 网络中断、Ollama 进程失联（`ECONNRESET`/`EPIPE`） | 是（恢复后继续） |
| `FR-TRANS-006` | 返回非法 | 条数/长度不匹配、空串、**占位符多重集被破坏**（§9.4 verify） | 是（丢弃本次结果 + 重试 1 次） |
| `FR-TRANS-007` | 术语表冲突 | 同一 `source` 映射多个不同 `target`（§5.1 去重） | 否（保留先出现者 + warn） |
| `FR-TRANS-008` | 文本过长 | 单段落超分批上限且无法按句拆分 | 否（按句拆分后继续） |
| `FR-TRANS-009` | 目标语言与原文相同 | 语言检测结果 === `targetLang` | 否（提示更换目标语言） |
| `FR-TRANS-010` | 本地模型不可用 | Ollama 未安装/未启动/模型未拉取（`ECONNREFUSED`） | 用户确认后重试 |
| `FR-TRANS-011` | 翻译被取消 | `AbortSignal` 触发（用户取消/切换文档） | 否 |
| `FR-TRANS-012` | 词典模式仅支持短文本 | `none` Provider 收到 `texts.length > 1` 或单条 > `TRANSLATE_DICT_MAX_CHARS`（§3.3） | 否 |
| `FR-TRANS-013` | 术语强制替换断言未过 | §5.3 断言：译文仍含 `source` 且 `source !== target` | 否（转人工复核，P0 缺陷） |
| `FR-TRANS-014` | 术语表导入非法 | 缺列/坏 `caseSensitive`/非 UTF-8；报文含**行号** | 否 |
| `FR-TRANS-015` | 缓存损坏 | SQLite 行不可解析 / JSONL 截断 | 否（自动重建 + warn） |
| `FR-TRANS-016` | 批量超限 | 单批 > `TRANSLATE_BATCH_CHARS`（编程错误，不得靠重试掩盖） | 否 |
| `FR-TRANS-017` | 部分批次失败 | 某个批在重试/拆半后仍失败（其余批次照常回填） | 否（UI 提供"重试失败段"） |

用户文案一律走 `11-error-handling.md` 的 i18n key：`errors.FR-TRANS-xxx`（如 `FR-TRANS-002` → `errors.FR-TRANS-002`；`FR-TRANS-001` 特例用 `translation.providerMissing`、`FR-TRANS-007` 用 `translation.glossary.conflict`、`FR-TRANS-009` 用 `translation.lang.sameAsSource`）。被 `NetGuard` 拦截时**透传** `FR-NET-00x`，不包装成 `FR-TRANS-*`。

## 3. 内置实现（三种）

```ts
// packages/core/src/budgets.ts（追加，禁止散落魔数）
export const TRANSLATE_BATCH_CHARS = 4000;      // 已存在（00-conventions §9）
export const TRANSLATE_TIMEOUT_MS = 30_000;     // 单批超时
export const TRANSLATE_MAX_RETRIES = 2;
export const TRANSLATE_CONCURRENCY_LOCAL = 1;   // 本地 Provider 全局并发
export const TRANSLATE_CONCURRENCY_REMOTE = 2;  // 远端 Provider 全局并发
export const TRANSLATE_DICT_MAX_CHARS = 120;    // 超此长度不用词典兜底
```

请求参数**冻结**：`temperature = 0.2`、`top_p = 0.9`（Ollama 额外 `seed = 0`）。端点拒绝这些参数时抛 `FR-TRANS-006`，**不得**静默降级为随机采样（否则缓存键失效、译文不可复现）。

**① `ollama`（本地默认，零上传）**

| 配置键 | 默认值 | 说明 |
|---|---|---|
| `translator.ollama.baseUrl` | `http://127.0.0.1:11434` | **唯一允许 `http://` 的例外**（`09` §2.4） |
| `translator.ollama.model` | `qwen2.5:7b-instruct` | 备选 `qwen2.5:14b-instruct`、`llama3.1:8b-instruct`、`gemma2:9b-instruct` |
| `translator.ollama.keepAlive` | `5m` | 传给 `/api/chat` 的 `keep_alive` |
| `translator.ollama.numCtx` | `8192` | 必须 ≥ 批字符数 × 2 |

- 请求：`POST /api/chat`，body `{ model, messages: [system, user], stream: false, format: 'json', options: { temperature: 0.2, top_p: 0.9, seed: 0, num_ctx } }`；仅当 `/api/chat` 返回 404（旧版）才回退 `/api/generate`；
- 未安装/未启动：`GET /api/version` 连接被拒（`ECONNREFUSED`）→ `FR-TRANS-010` + 安装引导（i18n `errors.FR-TRANS-010`）+ 一键回退 `none`；
- 模型未拉取：`GET /api/tags` 无目标模型 → `FR-TRANS-010`，提示 `ollama pull <model>`；超时：单批 30 s（→ `FR-TRANS-004`），`keepAlive` 冷启动仅首批放宽到 60 s；
- 重试：`ECONNREFUSED` **不重试**；`FR-TRANS-003/004/005` 指数退避 `500ms × 2^n + jitter(0..250ms)` ≤ 2 次；JSON 失败走 §9.4 加强指令重试 1 次；
- 并发 **1**（本地 GPU 争用会拉长总时长）；`health()` = `/api/version` 与 `/api/tags` 均 200。

**② `openai-compatible`（用户自带 baseUrl + key）** — 覆盖 DeepSeek / 通义 / Kimi / 自建 vLLM / OpenAI。

| 配置键 | 规定 |
|---|---|
| `translator.openai.baseUrl` | 必须 https，路径以 `/v1` 结尾；**每会话确认**（`09` §2.2） |
| `translator.openai.model` | 如 `deepseek-chat`、`qwen-plus`、`moonshot-v1-8k`、`Qwen2.5-7B-Instruct` |
| OS Keychain | 服务名 `freeread`，账户 `translator.openai.key`；**禁止**写入 `config.json`/日志（`00-conventions.md` §5） |
| `translator.openai.headers` | 仅 `string→string`；禁止覆盖 `Host`/`Content-Length`；经 `NetGuard` 头白名单过滤 |

- 请求：`POST {baseUrl}/chat/completions`，body `{ model, messages, temperature: 0.2, top_p: 0.9, response_format: { type: 'json_object' }, stream: false }`；端点返回 400 且报文含 `response_format` 时去掉该字段重试 1 次（部分自建 vLLM 不支持）；
- 超时 30 s（`FR-TRANS-004`）；重试：`FR-TRANS-003`（429/5xx）与 `FR-TRANS-004/005` 退避 ≤ 2 次（429 读 `Retry-After`，上限 10 s）；401/403 → `FR-TRANS-002`，按 11 §4 属"用户确认后重试"（**不自动重试**）；被 `NetGuard` 拦截 → 透传 `FR-NET-00x`；
- 并发 **2**（跨文档共享全局信号量）；
- 隐私：首次配置或更换 `baseUrl` 时弹确认框（i18n `translation.remote.consent`），文案含"本段文本将发送到 `<host>`；FreeRead 不保存你的文本"；
- `health()` = `GET {baseUrl}/models`；401/403 → `{ ok: false, detail: 'auth' }`。

**③ `none`（降级：仅划词词典）**

- `capabilities = ['offline']`；`translate()` 只接受 `texts.length <= 1 && texts[0].length <= TRANSLATE_DICT_MAX_CHARS`，否则 `FR-TRANS-012`（i18n `errors.FR-TRANS-012`）；
- 词库 **ECDICT**（英汉词典数据库），打包为 `resources/dict/ecdict.mini.sqlite`（仅 `word/phonetic/translation/tag/bnc/frq` 六列，约 40 MB），经 `better-sqlite3`（MIT）只读打开；
- **数据来源与许可**：`https://github.com/skywind3000/ECDICT`，其仓库声明为 **MIT**；打包前由 `pnpm license` 的 License Gate **人工复核 LICENSE 原文并存快照** `docs/license-snapshots/ecdict-LICENSE.txt`，同时写入 `THIRD_PARTY_NOTICES.md`；若复核与 MIT 不符（出现 NC/ND 条款），**立即移除词库**，退化为"空表 + 用户自建术语表"的 `allow-dict: false` 构建变体；
- 输出：`释义1；释义2`（≤ 3 条）；未命中返回原文 + "词典未命中"提示；`health()` 恒 `{ ok: true, model: 'ecdict' }`。

**Provider 选择**：`config.translator.order`（默认 `['ollama', 'openai-compatible', 'none']`）按序取首个 `health().ok` 者；`none` **必须**始终在末位且不可移除。运行中失败时**不自动切到远端**（避免用户在不知情下上传文本），仅确定性失败（如 `/api/tags` 为空）给"一键回退 `none`"。

## 4. 翻译单元与批处理

### 4.1 单元包含规则

| 来源 | 翻译 | 说明 |
|---|---|---|
| `Sentence.kind ∈ {text, title, caption}` | ✅ | 主路径 |
| `Sentence.kind === 'reference'` | ✅（默认开） | 设置项 `translator.translateReferences` |
| `Sentence.kind === 'formula'` | ❌ **必须跳过** | [`03 §6.5`](./03-anchor-model.md) 规则 1：整块为一个 `Sentence(kind='formula')`；**不得**把公式块当文本翻译 |
| `Block.type === 'inline_formula'` | ❌ | 文本中以 `\u0000fml:{blockId}\u0000` 占位（`03 §9`），占位符随句翻译 |
| `Block.type === 'abandon'` | ❌ | 页眉/页脚/水印/版权条 |
| `Block.type === 'table'` | ⚠️ V1 跳过 | 表格翻译列 V2；UI 提示"表格暂不翻译" |

**占位符哨兵**：发送前把控制字符占位符换成模型友好哨兵，返回后还原。

| 原文（`03` 定义） | 哨兵 | 还原 |
|---|---|---|
| `\u0000ref:N\u0000` | `⟦REF:N⟧` | `⟦REF:(\d+)⟧` → `\u0000ref:$1\u0000` |
| `\u0000fml:id\u0000` | `⟦FML:id⟧` | `⟦FML:([A-Za-z0-9_]+)⟧` → `\u0000fml:$1\u0000` |

### 4.2 批处理算法（伪码）

```
INPUT: orderedUnits（按 Paragraph.order + Sentence 出现顺序）；batchChars = TRANSLATE_BATCH_CHARS(4000)
1. units ← orderedUnits.filter(u => u.sentence.kind !== 'formula' && u.block.type !== 'abandon')
2. batches ← []; cur ← []; curChars ← 0; curPa ← null
3. for u in units:
     n ← u.text.length
     if n > batchChars:                     # 单句超长（罕见：无标点长段）
        flush(cur); batches.push([u]); warn 'translate.oversized'; continue
     if curPa !== null && u.paragraphId !== curPa: flush(cur)   # 不跨段落合并
     if curChars + n > batchChars: flush(cur)
     cur.push(u); curChars += n; curPa ← u.paragraphId
4. flush(cur)
5. RETRY per failed batch:
     attempt 1..TRANSLATE_MAX_RETRIES（退避 500ms×2^n + jitter）
     仍失败且 batch.length > 1 → 二分拆半递归（深度 ≤ 2）；仍失败 → batch.failed = true +
     error 'translate.batch.failed'（不阻塞其他批）
6. 回填：结果按 batchIndex/unitIndex 写入，**禁止**依赖完成顺序
7. 并发：信号量 = kind === 'local' ? 1 : 2（同一 Provider 全局共享）
```

**不变量（单测断言）**

| ID | 不变量 |
|---|---|
| TR-INV-1 | 输出 `texts.length === req.texts.length` 且逐元素索引一一对应 |
| TR-INV-2 | 任一批字符总量 ≤ `TRANSLATE_BATCH_CHARS`（超长独占批除外） |
| TR-INV-3 | 任一批不含 `kind='formula'` 的 `Sentence` |
| TR-INV-4 | 任一批的单元同属一个 `Paragraph`（超长单元除外） |
| TR-INV-5 | 回填顺序与 `orderedUnits` 一致，与批次完成顺序无关 |
| TR-INV-6 | 单批失败不影响其他批的回填（部分可用） |

## 5. 术语表（Glossary）

### 5.1 归一化与哈希

`GlossaryTerm = { source: string; target: string; caseSensitive?: boolean }`（`README.md` §3 冻结）。

- NFC + `trim()`；`source` 为空白 → 丢弃 + warn；`caseSensitive` 缺省 `false`；
- 去重键 = `caseSensitive ? source : source.toLocaleLowerCase('en-US')`；冲突（同一 `source` 映射多个不同 `target`）→ `FR-TRANS-007`，保留先出现者并记 warn；
- `glossaryHash = sha256(JSON.stringify(terms.map(t => [t.source, t.target, !!t.caseSensitive]).sort()))`，与输入顺序无关。

### 5.2 生效算法（发送前应用）

```
1. 按 source 构建 trie（构建期一次，随 glossaryHash 缓存）；caseSensitive=false 的条目插入时 casefold，
   匹配时对输入同样 casefold（保留原始下标，1:1 映射）
2. 扫描目标文本（不跨 Paragraph）：每个起点沿 trie 贪心前进并记录全部命中；冲突解决 = 最长匹配优先 →
   同长度 caseSensitive=true 优先 → 仍同则 source 字典序小者；已占用区间不可复用（非重叠，左到右贪心）
3. 产出 MatchPlan[] = { unitIndex, start, end, term }
4. 模式（知识库级 `glossary.mode`）：'auto'（默认）= 术语随提示词下发 + 校验阶段强制替换；
   'hint-only' = 仅下发提示，不强制替换（专有名词需保留原文时用）
```

### 5.3 译文校验断言（`auto` 模式强制）

```
for each (unit, match) in MatchPlan:
  T ← 归一化译文（NFC + 折叠连续空白）
  idx ← indexOfTerm(T, match.term.source, match.term.caseSensitive)
  if idx >= 0:
      if T.slice(idx, idx+len(target)) !== target:            # 模型未按术语输出
          T ← T.slice(0, idx) + target + T.slice(idx + len(source))
  else:
      T ← T + ' ' + target + '⟦GLOSSARY_FIX⟧'                  # 模型删/意译了术语 → 追加修正标记
  if indexOfTerm(T, term.source, true) >= 0 && term.source !== term.target:
      throw new AppError('FR-TRANS-013', { source: term.source })
```

- `indexOfTerm` 在 `caseSensitive=false` 时按 casefold 比较，但**替换区间用原始下标**；
- `⟦GLOSSARY_FIX⟧` 仅在渲染层表现为角标，用户可复核；指标要求 **术语命中率 = 100%**（§8.1），任何 `FR-TRANS-013` 均为 P0 缺陷。

### 5.4 导入 / 导出格式

| 项 | 规定 |
|---|---|
| 扩展名与编码 | `.csv`（逗号）或 `.tsv`（制表符）；UTF-8（允许 BOM）；非 UTF-8（GBK 等）先经 `iconv-lite` 转换并提示，仍失败 → `FR-TRANS-014` |
| 列与表头 | `source,target,caseSensitive`，表头**必填**（大小写不敏感匹配）；`#` 开头的行忽略（允许中文注释） |
| 引号 | RFC 4180：字段含分隔符/引号/换行须双引号包裹，`""` 为字面引号 |
| `caseSensitive` | `true`/`false`（大小写不敏感）；空 = `false`；其他值 → `FR-TRANS-014` 且报文含**行号** |
| 存储 | 库级 `library/<citekey>/glossary.csv`；共享表 `%APPDATA%/FreeRead/glossaries/<name>.csv`，由 `config.json` 的 `glossary.sharedFiles: string[]` 引用 |
| 导出 | 同格式，列序固定，行按 `source` 字典序（保证 diff 稳定） |

### 5.5 内置术语表来源与许可

**V1 不内置任何预置学术术语表**（避免来源不明的术语数据污染仓库）。交付物 = 空表模板 `packages/translate/assets/glossary.template.csv`（表头 + 3 行注释）。用户可在设置页"从当前文档批量添加"（IPC `fr:translate:upsertGlossary`）。未来若引入公开术语数据（UMLS/MeSH/Wikidata 等），引入 PR **必须**附：来源 URL、许可原文快照（`docs/license-snapshots/`）、`THIRD_PARTY_NOTICES.md` 条目、License Gate 通过记录；**禁止** CC-BY-NC/ND 或来源不明的数据（`README.md` F7）。

## 6. 缓存

### 6.1 缓存键与记录

```
cacheKey   = sha256(sourceHash + targetLang + providerId + modelId + glossaryHash)
sourceHash = sha256(NFC(unit.sourceText))      # 含哨兵替换后的原文
```

```ts
export interface TranslationRecord {
  key: string;                 // cacheKey（主键）
  docId: string; targetLang: string;            // BCP-47
  providerId: string; modelId: string; glossaryHash: string;
  unitKind: TranslationUnitKind;
  sampleId: string;            // Sentence.id / Paragraph.id：可回锚点，供回填与复核
  source: string; target: string;               // 原文（含控制字符占位符）/ 译文
  createdAt: number; lastUsedAt: number; hits: number; bytes: number;   // UTC 毫秒
}
```

> 与 [`plan §3.4 B`](../plan/FreeRead-技术方案与里程碑.md) 的 `translation_cache(doc_id, lang, paragraph_id, source_hash, target, provider, created_at)` 对齐；本规范**追加** `model_id`、`glossary_hash`、`cache_key` 三列（迁移归 `05-storage.md`；V1 该表可整体重建，**不 bump** 锚点 `schemaVersion`）。

### 6.2 存储（文件为真源，SQLite 为索引）

| 位置 | 内容 | 规则 |
|---|---|---|
| `library/<citekey>/translation/<lang>.jsonl` | `TranslationRecord` 一行一条 | **真源、可删可重建**；追加写；删除写 tombstone `{"key":"…","deleted":true}`，压缩时物理移除 |
| SQLite `translation_cache` | 同结构 + 索引 `(doc_id, target_lang)`、`(last_used_at)` | O(1) 查键与 LRU 扫描；可由 JSONL 重建（`freeread doctor --rebuild`） |
| `%APPDATA%/FreeRead/cache/translation/` | 仅跨文档共享条目（划词短语） | 同结构，独立配额（100 MB） |

**与 `05-storage.md` §5/§6 的字段映射（必须成对实现，禁止各写一套）**

| 05 字段 | 08 字段 | 说明 |
|---|---|---|
| `unit` / `unitId` | `unitKind` / `sampleId` | 一一对应（`sentence`/`paragraph`） |
| `sourceHash` | `sourceHash`（`cacheKey` 的输入，见 §6.1） | **规范化必须用 05 §5 T2 定义**（NFC → trim → 连续空白折叠为 `0x20`），否则命中率归零 |
| `provider`（`<providerName>:<model>`） | `providerId` + `modelId` | 08 拆成两列以便缓存键与 `provenance` 展示 |
| `target` / `createdAt` | `target` / `createdAt` | 一致（`createdAt` 为 UTC 毫秒；JSONL 序列化时额外写 ISO 或毫秒整数由 05 决定） |
| — | `glossaryHash` + `cacheKey` | 08 新增，需 05 同步扩列（见变更记录） |
| — | `lastUsedAt` / `hits` / `bytes` | 08 新增（LRU 与配额所需），SQLite 侧可只存索引需要的最小集 |

> 读取判定沿用 05 §5 T4 的语义：**`unitId` 相同 + `sourceHash` 相同 + provider 相同**即命中；08 的 `cacheKey` 等价于把该判定一次性哈希化，两种实现必须给出同一答案（单测 TT11/TT13 覆盖）。

### 6.3 失效规则

| 变化 | 结果 |
|---|---|
| 源文本变化（纠错 patch、重解析） | `sourceHash` 变 → 键变；旧条自然失配，**不主动删除** |
| 术语表变化（增删改/模式切换） | `glossaryHash` 变 → 键变；**在飞批次**必须沿用请求开始时的快照 |
| Provider / 模型变化 | `providerId`/`modelId` 变 → 键变；`none` 与 LLM 结果永不互串 |
| 目标语言变化 | 不同文件 + 不同键 |
| 提示词版本变化（`PROMPT_REVISION`） | 键**不含**提示词版本 → 变更时必须 bump `PROMPT_REVISION` 并执行 `freeread translate purge --all`（列入发布清单） |
| 用户手动编辑译文 | 覆盖同键 `target` 并置 `edited: true`；后续缓存写入**禁止**覆盖该记录 |

### 6.4 容量与清理

- 配额：**200 MB/知识库**，`cache/translation/` 另计 100 MB（与 `BUDGETS.CACHE_MAX_MB = 500` 共同约束）；
- 触发时机：启动后空闲 30 s、导入结束、写入后超配额；策略：按 `lastUsedAt` **LRU 淘汰至配额的 90%**，记 `info 'translate.cache.evict'`（`count`/`freed_mb`）；
- 过期：`lastUsedAt > 180 天` 且 `hits === 0` 者压缩时删除；命中过者不因时间删除（仅受容量约束）；
- 压缩：tombstone 占比 > 30% 或行数 > 10 万时重写（原子替换：写 `.tmp` → `fsync` → `rename`）；
- 用户可"清空本库翻译缓存"（`fr:translate:clearCache`），**不得**影响 `paper.pdf`/`blocks.json`/笔记。

## 7. 划词翻译

```
1. renderer 捕获选区，映射为锚点：a. 落在若干 Sentence 内 → unitKind='selection'，附 sentenceIds[]；
   b. 覆盖公式占位符 → 保留占位符，公式不翻译、原样输出；c. 跨 Paragraph → 按 Paragraph 切段后拼接
2. 长度校验（trim 后按 code point）：min = 2；max = 5000
   - < 2 → 不发请求，不显示浮层；- > 5000 → 先按句边界拆为 ≤ 4000 字符的块，仍超限才截断并提示
3. 归一化：NFC + 折叠空白 + 去软连字符 U+00AD；4. 查缓存键（§6.1），命中直接返回且不发请求
5. 未命中：长度 ≤ TRANSLATE_DICT_MAX_CHARS 且 Provider 为 none → 词典兜底（§3.3）；否则走单条批
6. 渲染：浮层显示译文 + Provider 徽标（local/remote）+「加入术语表」；remote 时显示"已发送至 <host>"
7. 划词译文只写 cache/translation/ 共享缓存（unitKind='selection'），**不写**库内段落对照 JSONL
```

**离线词典兜底（`none`）**：触发条件 = `providerId === 'none'` 或全部 Provider `health()` 为 false；命中显示 `word / phonetic / translation`；多词短语无整条命中时逐词显示（≤ 6 词，超出只显示首词 + 提示）；未命中显示 i18n `translation.dict.miss`，**不得空白**。划词浮层是临时 UI，**不产生** `Annotation`（与 [`report §5.5`](../report/Scholaread-调研报告.md)"译文模式禁用高亮/笔记"的锚点一致性原则同源）。

## 8. 质量与验收

### 8.1 指标卡（登记进 `10-testing.md`）

| 指标 | 定义 | 阈值 | 门禁 |
|---|---|---|---|
| 术语命中率 | ≥ 100 条黄金术语在 50 篇黄金集上强制替换成功比例 | **100%** | P0 |
| 公式占位符保留率 | 送审 `⟦FML:*⟧`/`⟦REF:*⟧` 在译文中多重集完全一致的比例 | **100%** | P0 |
| JSON 解析成功率 | 首次响应即产出合法 JSON 数组（未触发重试）的比例 | **≥ 99%** | P0 |
| 端到端时延 | 1000 词段落批翻（本地 7B，草稿机，非冷启动） | **≤ 8 s** | P0（M4 Gate） |
| 批次效率 | 平均批字符数 / `TRANSLATE_BATCH_CHARS` | ≥ 0.75 | P1 |
| 缓存命中率 | 二次打开同文档的命中批占比 | ≥ 90% | P1 |
| 降级可用性 | 断网 + 无 Ollama 时核心阅读与划词词典可用 | 100% | P0 |
| 不变量 | TR-INV-1..6 | 100% | P0 |

### 8.2 必须存在的单测（`packages/translate/src/**/*.test.ts`）

| # | 用例 | 断言 |
|---|---|---|
| TT1 | 5 段共 12 000 字符 | 切 ≥ 3 批，每批 ≤ 4000，TR-INV-2/4 成立 |
| TT2 | 批 2 先返回、批 1 后返回 | 结果顺序 === 输入顺序（TR-INV-5） |
| TT3 | `kind='formula'` 的单元 | 不出现在任何批次（TR-INV-3） |
| TT4 | 失败批拆半 | 首次失败 → 拆半 → 两半成功，无 `failed` |
| TT5 | 术语最长匹配 | `["cell","cell line"]` + 文本 `cell line` → 命中 `cell line` |
| TT6 | 术语大小写 | `caseSensitive=true` 时 `Cell`≠`cell`；`false` 时命中且按下标替换 |
| TT7 | 术语强制替换 | mock 不返回 target → `FR-TRANS-013` 或写入 `⟦GLOSSARY_FIX⟧` |
| TT8 | 占位符保留 | mock 丢弃 `⟦REF:3⟧` → `FR-TRANS-006` |
| TT9 | JSON 解析 | 带 ```json 围栏 → 正常解析；连续 2 次非法 → 按行切分兜底且长度对齐；仍不对齐 → `FR-TRANS-006` + `FR-TRANS-017` |
| TT10 | 译文为空 | 空串/仅空白 → `FR-TRANS-006` 且重试 1 次 |
| TT11 | 缓存键 | 五元组（源文本/targetLang/providerId/modelId/glossaryHash）任一变化 → 键变化（5 断言） |
| TT12 | 缓存命中与 LRU | 二次调用 mock 次数 === 1；超配额后按 `lastUsedAt` 淘汰至 90%，最新命中保留 |
| TT13 | JSONL 往返 | 写入 → 重建 SQLite → 结果逐字节一致；损坏行 → `FR-TRANS-015` + 自动重建 |
| TT14 | 划词长度 | 1 字符不请求；5001 字符被拆；2 字符发起；`none` 超 120 字符或多段 → `FR-TRANS-012` |
| TT15 | 超时与鉴权 | 30 s abort → `FR-TRANS-004` 且重试 ≤ 2 次；401 → `FR-TRANS-002` 且**不自动重试**（mock 次数 === 1） |
| TT16 | 术语表导入 | 缺列/坏 `caseSensitive`/GBK → `FR-TRANS-014` 且报行号；重复 `source` → `FR-TRANS-007` + warn |

**必须提供的 Mock Provider**：`packages/translate/src/testing/mock-provider.ts`，支持 `{ delayMs, failTimes, mode: 'echo'|'prefix'|'json-broken'|'drop-placeholder'|'drop-glossary' }`，并记录 `calls: TranslateRequest[]` 供断言（全仓复用）。

### 8.3 提示词版本

```ts
export const PROMPT_REVISION = 1;   // packages/translate/src/prompt.ts
```

任何系统提示词或校验规则改动必须 +1 并在本文件变更记录登记；`12-build-release.md` 的发布清单必须包含"`PROMPT_REVISION` 变化 → 提示用户清理翻译缓存"。

## 9. 提示词规范

### 9.1 中文系统提示词（`SYSTEM_PROMPT_ZH`）

```text
你是学术文献翻译引擎，服务于科研人员的论文精读。
任务：把用户给出的 JSON 数组中的每个字符串翻译成 {TARGET_LANG}，并以 JSON 数组返回。

硬性要求：
1. 只输出译文：不解释、不评论、不加前言后语、不输出 Markdown 代码围栏。
2. 顺序与数量严格对应：输入 N 个字符串就返回 N 个字符串，第 i 个输出是第 i 个输入的译文；输出必须是 JSON 数组（形如 ["译文1","译文2"]），字符串内不得出现未转义的换行。
3. 术语一致：术语表给出的“源词 => 译词”必须在译文中原样使用该译词，不得意译、不得改写。
4. 原样保留所有占位符：形如 ⟦REF:12⟧、⟦FML:b_3_7⟧ 的标记必须逐字符原样出现在译文对应位置，不得翻译、不得增删、不得改动数字或大小写、不得移动顺序。
5. 不增删内容：不得添加原文没有的信息，不得省略从句、限定语、数字、单位与否定。
6. 学术语体：使用规范的学术书面语；术语按学科惯例翻译；缩写首次出现保留英文原形并加中文译名（如“支持向量机（SVM）”）。
7. 数字、公式变量、单位、化学式、基因/蛋白名、代码标识符保持原样；无法确定的术语保留英文原词，不要臆造译名。

上下文（仅用于消歧，不要翻译、不要在译文中体现）：文档标题：{DOC_TITLE}；学科领域：{FIELD}
```

### 9.2 English system prompt (`SYSTEM_PROMPT_EN`)

```text
You are an academic translation engine serving researchers reading papers.
Task: translate every string in the user-provided JSON array into {TARGET_LANG} and return a JSON array.

Hard requirements:
1. Output translations only: no explanations, no commentary, no preamble, no Markdown code fences.
2. Keep order and count exact: N inputs produce N outputs; output[i] is the translation of input[i]; the output must be a JSON array, e.g. ["译文1","译文2"], with no unescaped newlines inside strings.
3. Glossary consistency: for every "source => target" pair, use exactly that target wording.
4. Preserve every placeholder verbatim: ⟦REF:12⟧ and ⟦FML:b_3_7⟧ must appear character-for-character at the corresponding position; never translate, add, remove, renumber, re-case, or reorder them.
5. No additions, no omissions: do not add absent information and do not drop clauses, qualifiers, numbers, units, or negations.
6. Academic register: formal scholarly prose; keep symbols, units, chemical formulas, gene/protein names, and code identifiers unchanged; keep abbreviations with their full form on first use.
7. If a term is genuinely unknown, keep the English original instead of inventing a translation.

Context (for disambiguation only; never translate it and never echo it): Document title: {DOC_TITLE}; Field: {FIELD}
```

**用户消息载荷（`USER_PAYLOAD`，双语一致）**

```json
{"glossary":[{"source":"cell line","target":"细胞系"},{"source":"in vitro","target":"体外"}],
 "context":{"docTitle":"…","field":"molecular biology"},
 "texts":["The ⟦REF:3⟧ cell line was cultured in vitro for 72 h.","…"]}
```

语言选择：`to` 以 `zh` 开头 → `ZH`，否则 → `EN`；`{DOC_TITLE}`/`{FIELD}` 缺失时填 `"（未知）"`/`"(unknown)"`，**不得**留空花括号；`context.surroundingText` **不**进提示词（仅本地消歧与日志），避免浪费 token。

### 9.3 Few-shot 示例（随系统提示词发送，`PROMPT_REVISION = 1` 冻结）

```json
// 示例 1：术语 + 引用占位符 + 单位
// user
{"glossary":[{"source":"in vitro","target":"体外"}], "texts":["The ⟦REF:3⟧ assay was performed in vitro at 37 °C."]}
// assistant
["该⟦REF:3⟧检测在 37 °C 下体外完成。"]

// 示例 2：公式占位符 + 否定 + 缩写
// user
{"glossary":[], "texts":["Unlike SVM, the proposed ⟦FML:b_3_7⟧ model did not require feature normalization."]}
// assistant
["与支持向量机（SVM）不同，所提出的⟦FML:b_3_7⟧模型不需要特征归一化。"]
```

### 9.4 输出解析与校验

```
parse(raw):
 1. 裁剪首尾空白；若被 ```json / ``` 围栏包裹 → 去围栏
 2. 取第一个 '[' 到最后一个 ']' 的子串 → JSON.parse
 3. 校验 Array.isArray && 全为 string && length === texts.length → 成功（metric 'translate.parse.ok'）
 4. 失败 → 第 1 次重试：追加指令"上一次输出不是合法的 JSON 数组。只输出 JSON 数组，不要任何其他字符。"（仅重试时 temperature = 0）
 5. 仍失败 → 按行切分兜底：按 '\n' 切分，去空行与围栏行；行数 === texts.length → 逐行作为译文；
    否则抛 FR-TRANS-006（返回非法），该批标 failed 并抛 FR-TRANS-017（部分批次失败，不阻塞其他批）；
    兜底成功记 warn 'translate.parse.fallback'（计为成功率的负例）

verify(每一条译文):
 - 占位符多重集必须与原文完全相等；不等 → 按原文顺序回填缺失占位符；仍不等 → FR-TRANS-006
 - 空/仅空白 → FR-TRANS-006（该批重试 1 次）；术语断言（§5.3）失败 → FR-TRANS-013
 - 与原文逐字节相同且含字母 → warn 'translate.identity'，UI 显示"未翻译"
 - 还原哨兵：⟦REF:n⟧ → \u0000ref:n\u0000；⟦FML:id⟧ → \u0000fml:id\u0000
```

**提示词注入防护**：正文可能含"忽略以上指令"类文本。系统提示词与用户载荷分属不同 message 角色，正文只作为 JSON 字符串出现在 `texts` 中；解析阶段仅接受 JSON 数组形态，任何附加说明段落都会被 §9.4 校验拒绝。

## 10. 与其它规范的接口

出站请求 → [`09`](./09-fetch-compliance.md)：一律经 `NetGuard.request()`（本文用名；`06-ipc-contract.md` 的 `NetGuardContext` 即本文 `NetContext`），本地 `127.0.0.1` 例外，审计 `purpose: 'llm'`。翻译单元 → [`03`](./03-anchor-model.md)：只读 `Sentence`/`Paragraph`，公式 `kind='formula'` 与 `\u0000fml:\u0000` 占位符。存储 → `05-storage.md` §5（`translation/<lang>.jsonl`，其"读最后一条 + `sourceHash` 匹配"的规则由本文 §6.1 的 `cacheKey` 实现并扩展三列）。IPC → `06-ipc-contract.md`：`fr:translate:translateUnits` 的允许码需补 `FR-TRANS-007/011..017`、`fr:translate:upsertGlossary` 需补 `FR-TRANS-014`（同 PR 更新该通道表）。渲染 → `07-ui-spec.md`（译文 `<span class="translation" data-sentence-id>`）。错误 → `11-error-handling.md` §3（本表 `FR-TRANS-001..010` 与其逐条一致；`011..017` 为本文新增，登记 PR 见 §变更记录）。

## 变更记录

| 版本 | 日期 | 变更 | 影响 |
|---|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：`TranslatorProvider` 接口、三种内置实现、批处理 TR-INV-1..6、`PROMPT_REVISION = 1` 提示词与 2 条 few-shot、术语强制替换算法、缓存键与 LRU、划词流程、指标卡与 16 条单测 | **同 PR 必须完成**：① `11-error-handling.md` §3 登记 `FR-TRANS-011..017`（`001..010` 语义以 11 为准，本文逐条对齐）；② `06-ipc-contract.md` 的 `fr:translate:translateUnits` 允许码补 `FR-TRANS-007/011..017`、`fr:translate:upsertGlossary` 补 `FR-TRANS-014`；③ `05-storage.md` §5/§6 为 `translation/*.jsonl` 与 `translation_cache` **追加 `glossary_hash`、`cache_key`（及 `model_id`、`last_used_at`、`hits`、`bytes`）**；V1 该表可整体重建，不 bump 锚点 `schemaVersion` |
