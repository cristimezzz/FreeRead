# 06 · IPC 契约（Renderer ↔ Main）

> 状态：**冻结**。机器可读真源 = [`schemas/ipc-channels.json`](./schemas/ipc-channels.json)；本文是它的人读版本，**通道名、错误码、类型名必须与之一致**（`node specs/tools/check-specs.mjs` 的 C6/C7/C8 机检该约束，不一致即失败）。
> 上游：[README §3 命名 / §4 模块边界 / F1](README.md) ｜ [00-conventions §2 §4](00-conventions.md) ｜ [03-anchor-model](03-anchor-model.md) ｜ [04-parser-sidecar §2 §5](04-parser-sidecar.md) ｜ [05-storage §4 §11](05-storage.md) ｜ [11-error-handling](11-error-handling.md) ｜ [09-fetch-compliance](09-fetch-compliance.md)（NetGuard）

---

## 1. 设计原则

| # | 原则 | 落地与机检 |
|---|---|---|
| P1 | **renderer 零特权**：渲染进程不得 `import` `fs`/`net`/`child_process`/`electron`（README **F1**），不得直接发起任何 HTTP 请求（**F2**） | `eslint-plugin-boundaries` + `no-restricted-imports`（00-conventions §4）；preload 不暴露任何 Node 能力 |
| P2 | **preload 只暴露白名单方法**：`window.fr.<domain>.<action>(req)` 一一对应 `channels[]`；**禁止**暴露通用 `invoke(channel, payload)`、`send`、`ipcRenderer` 或 `require` | `apps/desktop/src/preload/bridge.generated.ts` 由 `pnpm gen` 生成；`contextIsolation: true`、`nodeIntegration: false`、`sandbox: true` |
| P3 | **显式声明**：每个通道必须在本文件与 manifest 中同时声明「载荷 schema / 返回值 / 失败错误码 / since」，未声明即拒绝（`FR-IPC-001`） | 主进程 handler 注册表 `registry.generated.ts` 只含 `channels[]`；运行时对未知通道抛 `FR-IPC-001` |
| P4 | **禁止传递 Electron 对象**：`BrowserWindow`/`WebContents`/`IpcMainEvent`/`Event`/`Error`/`Buffer` 一律不得出现在载荷或返回值中；跨进程只允许 JSON 值 | 载荷 zod 严格校验（拒绝 `Date`/`Buffer`/函数/`undefined`）；`Error` 必须先转 `AppErrorWire`（11 §1.2 E-2） |
| P5 | **主进程是唯一写入者**：renderer 不传绝对路径（除 P6 的五处入口）、不传文本原文（除划词）、不传 `citekey` 目录名之外的文件标识；Agent/项目通道中的文件一律用**工作区相对路径** | 见 §5 与 §4.5 |
| P6 | **路径最小面**：仅 `fr:library:import`（`source.path`）、`fr:library:importFolder`（`dirPath`）、`fr:app:setConfig`（`libraryPath`/`cachePath`）、`fr:project:importFiles`（`sourcePaths[]`）、`fr:agent:installSkill`（`sourceDir`）五处接受绝对路径，且都必须是**用户经系统对话框/拖放显式选择**的来源，全部经 §5.2 校验；`fr:agent:send` 的附件只允许 `docId` 或工作区相对路径（§5.2 **A5**） | 越权用例见 §8.3 |
| P7 | **一切失败都是 `AppError`**：跨 IPC 只传 `AppErrorWire`；错误码必须在 [11-error-handling §3](11-error-handling.md) 登记 | `toAppError` 位于 handler 最外层（11 §1.2 E-4①） |

```ts
// apps/desktop/src/preload/bridge.generated.ts（形状示意，禁止手写）
export interface FrBridge {
  readonly library: {
    list(req: LibraryListRequest): Promise<ApiResult<LibraryListResponse>>;
    /* … channels[] 中 fr:library:* 的其余方法 … */
  };
  /* … doc / parser / notes / translate / fetch / zotero / app / window … */
  /** 订阅主→渲染事件；返回取消订阅函数。事件名同样受白名单约束。 */
  on<T extends FrEventName>(type: T, handler: (event: FrEvent<T>) => void): () => void;
}
declare global { interface Window { readonly fr: FrBridge } }
// 反例（禁止生成）：invoke(channel: string, payload: unknown): Promise<unknown>
```

---

## 2. 统一信封

### 2.1 TypeScript 类型

```ts
// packages/core/src/ipc.ts
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: AppErrorWire };          // 11-error-handling §1.1

export interface AppErrorWire {
  code: string;                                  // FR-<AREA>-<3位>，必须已登记
  message: string;                               // 英文，面向开发者
  category: ErrorCategory;                       // input|parse|storage|network|provider|ipc|ui|system|compliance|unknown
  severity: 'fatal' | 'error' | 'warn';
  retryable: boolean;
  i18nKey: string;                               // 形如 errors.FR-IPC-002
  details?: Record<string, string | number | boolean | null>;
}

/** manifest 中 channels[].response 描述的是 data 的载荷类型 T。 */
export type FrEvent<T> = { type: FrEventName; payload: T; ts: number; seq: number };
```

- 每个 invoke 通道返回且仅返回 `ApiResult<T>`；`ok` 是唯一判别式，**禁止**再用 `success`/`err` 等别名。
- 所有返回值必须被 `channels[].response` 对应的 zod 严格 schema 校验后才发给 renderer；响应对象里出现 schema 未声明的字段即为实现缺陷（`pnpm gen:check` + 契约测试捕获）。
- `details` 只允许 `string|number|boolean|null`；**禁止**写入密钥、笔记全文、译文全文、含用户名的绝对路径（00-conventions §5）。

### 2.2 完整示例

```jsonc
// 成功：fr:library:get  →  renderer 收到 window.fr.library.get({ citekey: 'smith2020-attention' })
{ "ok": true,
  "data": { "item": {
    "docId": "9f2c0b1a4e5d678901234567890abcdef1234567890abcdef1234567890abcdef",
    "citekey": "smith2020-attention",
    "meta": { "schemaVersion": 1, "citekey": "smith2020-attention", "docId": "9f2c…cdef",
              "title": "Attention Is All You Need", "authors": ["Vaswani, A."], "tags": ["nlp"],
              "collections": [], "addedAt": "2026-10-03T00:12:00Z", "updatedAt": "2026-10-03T00:12:00Z",
              "source": { "kind": "local-file" } },
    "pageCount": 15, "parserEngine": "docling", "parserVersion": "2.5.1",
    "readState": "reading", "readProgress": 0.42, "tags": ["nlp"],
    "hasAnchorModel": true, "hasNotes": true, "present": true } } }

// 失败：同一通道，文档不存在
{ "ok": false,
  "error": { "code": "FR-LIB-005", "message": "paper.pdf is missing for citekey smith2020-attention",
             "category": "input", "severity": "error", "retryable": true,
             "i18nKey": "errors.FR-LIB-005",
             "details": { "citekey": "smith2020-attention" } } }
```

### 2.3 事件（主 → 渲染）

事件**不受** invoke 信封约束，但每个事件必须同时具备 `type` 与 `payload`（外加 `ts`、`seq`）：

```jsonc
{ "type": "fr:parser:progress",
  "payload": { "docId": "9f2c…cdef", "citekey": "smith2020-attention", "jobId": "job_01J8ZQ4K7M",
               "progress": 0.42, "stage": "layout", "state": "running",
               "pagesDone": 21, "pagesTotal": 50, "etaMs": 8400 },
  "ts": 1759449600123, "seq": 7 }
```

- `seq` 在同一 `webContents` 内**每通道**从 1 单调递增；渲染端发现跳号 → 记 `warn: ipc.event.gap` 并重新拉取全量状态（`fr:library:list` / `fr:parser:health` / `fr:notes:list`）。
- 事件是**通知而非真源**：`fr:library:changed` / `fr:notes:changed` 只用于失效缓存，任何状态都必须能由 invoke 通道重新查询得到。
- `fr:parser:progress` 的节流与最小载荷冻结于 [04-parser-sidecar §5](04-parser-sidecar.md)：必填仅 `docId`/`jobId`/`progress`/`stage`，节流 ≥ 100 ms，状态跃迁必发。
- 终态失败用独立事件 `fr:parser:failed`（04 §2.2），带完整 `error`；不与进度事件混用。
- `fr:agent:event` 的载荷是 `{sessionId, seq, kind, payload}`（[14-agent §11](14-agent.md)）：**外层信封的 `seq`**（同一 `webContents` 内每通道单调递增）与**载荷内的 `seq`**（会话事件序号，用于 `fr:agent:getSession` 的 `afterSeq` 增量）语义不同，**不得混用**。会话事件流是 append-only 的**回放真源**（AG-7），`fr:agent:event` 只是实时通知；renderer 断线/跳号后必须用 `fr:agent:getSession` 补齐。
- **run 级失败一律经事件回推**：run 开始之后的失败（`FR-AGT-002` 模型调用失败/超时、`FR-AGT-004` 工具参数非法、`FR-AGT-005` 工具执行失败、`FR-AGT-006` 步数/工具数超限、`FR-AGT-007` 取消、`FR-AGT-008` 沙箱越界、`FR-AGT-010` 会话损坏、`FR-AGT-011` 上下文超预算）以 `kind:'error'`（或 `run_state` 的 `reason`）回推，**不**用 `fr:agent:send` 的 `ok:false` 表达（`send` 早已在 run 开始前返回 `runId`）。
- `fr:project:changed` 同 `fr:library:changed`：只用于失效缓存，`projectId` 指向的状态必须能由 `fr:project:listFiles` / `fr:project:getPermissions` 重新查到。

### 2.4 公共错误码

所有 invoke 通道在 manifest 的 `commonErrors` 中**隐含**携带以下 4 个码，通道表只列域特有码（表中记作 **`+C`**）：

| 码 | 含义 | 触发 |
|---|---|---|
| `FR-IPC-001` | 通道未注册 | 请求不在 `channels[]` 白名单（fatal，不重试） |
| `FR-IPC-002` | 载荷校验失败 | zod 严格校验不通过；**含**路径非法、未知引用 id、批量超限、FTS 语法错误等**进程内**语义校验（见 §5.4）。网络与合规类拒绝用 `FR-NET-002`/`FR-NET-003`，**不**用本码 |
| `FR-IPC-003` | 通道超时 | handler 无响应 > 30 s（可重试 1 次） |
| `FR-SYS-001` | 未预期异常兜底 | 穷尽分支 `never` 命中或未知 throw |

**错误码 vs 降级（`errors` / `warnings` 的判据）**：判据是「**操作是否可完成**」，不是级别。

| 情形 | 返回 | 例 |
|---|---|---|
| 操作**无法完成** | `ok:false` + `error.code` ∈ 该通道 `errors[]` | `FR-LIB-004` 格式不支持、`FR-LIB-005` 文件缺失、`FR-NET-003` 合规拦截 |
| 操作**可完成但有降级** | `ok:true` + `warnings[]` 含 warn 级码 | `FR-LIB-003` 文件过大、`FR-LIB-006` 重复导入、`FR-PARSE-001`/`FR-PARSE-002` 已切快速模式、`FR-PARSE-009` 分批解析、`FR-STORE-005` 索引不一致、`FR-STORE-007` 缓存不可写、`FR-STORE-008` 配置损坏已恢复默认、`FR-ANCHOR-011` 锚点失效已就近定位 |

- **禁止**用 `ok:false` 表达降级（11 §5 D-2：降级必须**可见**但不得阻断阅读）；反之，把「无法完成」伪装成 `ok:true` 同样是缺陷。
- 带 `warnings` 字段（必填，可为空数组）的响应：`LibraryImportResponse`、`LibraryImportFolderResponse`、`LibraryRemoveResponse`、`LibraryUpdateMetaResponse`、`LibraryReindexResponse`、`DocGetPageBitmapResponse`、`ParserStartResponse`、`ParserConsentModelDownloadResponse`、`ZoteroImportSelectionResponse`、`AppGetConfigResponse`、`AgentStartResponse`、`AgentGetSessionResponse`、`AgentListToolsResponse`、`AgentInstallSkillResponse`、`ProjectEnsureResponse`、`ProjectImportFilesResponse`、`ProjectExportZipResponse`。
- §3 通道表的「失败错误码」列**只列 `ok:false` 的码**（= manifest `channels[].errors`，机检一致）；warn 级码在备注列以 `warn:` 前缀标出，并随上表名单中响应的 `warnings` 字段回传。
- **Agent 的 run 级失败不走 invoke 信封**：`fr:agent:send` 只表达「能否受理」——`ok:false` 仅用于「无可用 Provider」（`FR-AGT-001`，warn 级但操作无法完成，同 `FR-FETCH-001` 的先例）、项目工作区不可用（`FR-AGT-012`）、写盘失败（`FR-STORE-*`）与载荷非法（`FR-IPC-002`）；run 开始之后的失败（`FR-AGT-002/004/005/006/007/008/010/011`）经 `fr:agent:event` 的 `kind:'error'` 回推，其 `payload.code` 必须已登记在 [11-error-handling §3](11-error-handling.md)。
- **`agent:false` 不在 V1 出现**（§6.1）：`fr:app:getCapabilities` 恒返回 `agent:true`，故 §6.3 中该行为纯预留。

---

## 3. 通道表

方向记法：**R→M** = invoke（renderer 调用、主进程实现，返回 `ApiResult<T>`）；**M→R** = 事件。类型名对应 manifest `$defs`；外部域对象用其 schema 名（`DocMeta`/`Annotation`/`DocAnchorModel`/`AppConfig`）。

### 3.1 `fr:library:*`（10）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:library:list` | R→M | `LibraryListRequest` | `LibraryListResponse` | `+C` | 强制分页（`offset`/`limit` 必填，`limit ≤ 200`），禁止无界查询 |
| `fr:library:get` | R→M | `LibraryGetRequest` | `LibraryGetResponse` | `FR-LIB-005` `+C` | `docId` 与 `citekey` **恰好一个** |
| `fr:library:import` | R→M | `LibraryImportRequest` | `LibraryImportResponse` | `FR-LIB-001` `FR-LIB-002` `FR-LIB-004` `FR-LIB-007` `FR-LIB-009` `FR-STORE-002` `FR-STORE-003` `FR-NET-001` `FR-NET-002` `FR-NET-003` `+C` | 本地路径或白名单 URL；去重命中 → `deduped:true`；`warn:` `FR-LIB-003`（过大）/`FR-LIB-006`（重复）走 `warnings[]` |
| `fr:library:importFolder` | R→M | `LibraryImportFolderRequest` | `LibraryImportFolderResponse` | `FR-STORE-002` `+C` | **逐文件容错**：单文件问题进 `failures[]`（其 `code` 取自 11 §3）不中断整批；仅根目录不可读/不可写才 `ok:false`；`warn:` `FR-LIB-003` |
| `fr:library:remove` | R→M | `LibraryRemoveRequest` | `LibraryRemoveResponse` | `FR-LIB-009` `FR-STORE-002` `+C` | `deleteFiles:true` → 移入 `.trash/`，禁止直接删除；文件已丢失**仍必须成功**（`warn:` `FR-LIB-005`，移除正是其修复动作） |
| `fr:library:rename` | R→M | `LibraryRenameRequest` | `LibraryRenameResponse` | `FR-LIB-005` `FR-LIB-007` `FR-LIB-009` `FR-STORE-002` `FR-STORE-003` `+C` | 原子重命名；citekey 被**其他** docId 占用才报冲突 |
| `fr:library:updateMeta` | R→M | `LibraryUpdateMetaRequest` | `LibraryUpdateMetaResponse` | `FR-LIB-005` `FR-LIB-009` `FR-STORE-002` `+C` | `DocMetaPatch` 无 `docId`/`citekey`/`addedAt`/`source` 字段，结构上不可改；`warn:` `FR-LIB-008`（值不合规时回退文件名补全） |
| `fr:library:reindex` | R→M | `LibraryReindexRequest` | `LibraryReindexResponse` | `FR-STORE-002` `FR-STORE-004` `+C` | 文件为真源；`verifyFiles:true` 只报差异（`drift`）不静默修复；`warn:` `FR-STORE-005`（存在差异） |
| `fr:library:listTags` | R→M | `LibraryListTagsRequest` | `LibraryListTagsResponse` | `+C` | 无参通道，载荷必须是 `{}` |
| `fr:library:setTags` | R→M | `LibrarySetTagsRequest` | `LibrarySetTagsResponse` | `FR-LIB-005` `FR-LIB-009` `+C` | `mode ∈ {replace,add,remove}`；`warn:` `FR-LIB-008`（标签被规范化后仍写入） |

### 3.2 `fr:doc:*`（7）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:doc:open` | R→M | `DocOpenRequest` | `DocOpenResponse` | `FR-LIB-005` `FR-ANCHOR-009` `+C` | 返回 `sessionId` 与 `fr-file://` 的 `pdfUrl`；`restored.degraded=true` 时 UI 必须显示位置恢复降级横幅 |
| `fr:doc:close` | R→M | `DocCloseRequest` | `DocCloseResponse` | `+C` | `closing` 阶段同步写 `ReadingProgress`；失败降级写 `OpLogEntry` 并回 `progressSaved:false` |
| `fr:doc:getAnchorModel` | R→M | `DocGetAnchorModelRequest` | `DocGetAnchorModelResponse` | `FR-LIB-005` `FR-ANCHOR-009` `+C` | 只读缓存，**绝不现场解析**；未解析 → `FR-LIB-005` |
| `fr:doc:getPageBitmap` | R→M | `DocGetPageBitmapRequest` | `DocGetPageBitmapResponse` | `FR-LIB-005` `+C` | 默认 `dpi=BUDGETS.PAGE_BITMAP_DPI(110)`/`webp`；推荐 `transport='protocol-url'`（`fr-cache://`）；`warn:` `FR-STORE-007`（缓存不可写则按需重生成） |
| `fr:doc:exportPatch` | R→M | `DocExportPatchRequest` | `DocExportPatchResponse` | `FR-LIB-005` `FR-ANCHOR-012` `+C` | 输出标准化 JSON + `sha256`，**不含绝对路径**，供社区汇总 |
| `fr:doc:applyPatch` | R→M | `DocApplyPatchRequest` | `DocApplyPatchResponse` | `FR-ANCHOR-010` `FR-ANCHOR-012` `+C` | 原子替换 `blocks.json`；失败整体回滚，`dryRun` 只校验 |
| `fr:doc:search` | R→M | `DocSearchRequest` | `DocSearchResponse` | `FR-LIB-005` `+C` | FTS5（`unicode61` + 应用层分词，05 §7.1）；`scope='doc'` 时 `docId` 必填 |

### 3.3 `fr:parser:*`（5）+ 2 事件

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:parser:start` | R→M | `ParserStartRequest` | `ParserStartResponse` | `FR-LIB-001` `FR-LIB-002` `FR-LIB-005` `FR-PARSE-003` `FR-PARSE-004` `FR-PARSE-008` `FR-PARSE-010` `FR-PARSE-012` `+C` | 幂等：同 `cacheKey` 返回既有 `jobId` 且 `reused:true`（不报错）；`engine` 接受 `auto`；**sidecar 缺失不失败** → `engine:'rule'` + `warn:` `FR-PARSE-001`/`FR-PARSE-002`/`FR-PARSE-009` |
| `fr:parser:cancel` | R→M | `ParserCancelRequest` | `ParserCancelResponse` | `+C` | 终态幂等 → `canceled:false` + 现状态；未知 `jobId` → `FR-IPC-002`(`reason=job_not_found`) |
| `fr:parser:health` | R→M | `ParserHealthRequest` | `ParserHealthResponse` | `+C` | 探测失败**不抛错**，返回 `ok:false`，避免降级路径被错误阻断 |
| `fr:parser:listEngines` | R→M | `ParserListEnginesRequest` | `ParserListEnginesResponse` | `+C` | 含模型体积/许可/`present`，驱动"是否需下载"确认框 |
| `fr:parser:consentModelDownload` | R→M | `ParserConsentModelDownloadRequest` | `ParserConsentModelDownloadResponse` | `FR-NET-003` `FR-STORE-001` `FR-STORE-002` `+C` | 写 `config.parser.consentToDownloadModels`；只回 `hosts`（域名）供合规展示；下载由主进程经 NetGuard 执行；离线/无 Python → `downloadStarted:false` + `warn:` `FR-NET-001`/`FR-NET-002`/`FR-PARSE-002` |
| `fr:parser:progress` | M→R | `ParseProgressEvent` | — | — | 节流 ≥ 100 ms；`stage ∈ {loading_model,layout,ocr,references,finalize}` |
| `fr:parser:failed` | M→R | `ParserFailedEvent` | — | — | 终态失败（04 §2.2）；不自动重放，由 `ParserClient` 按 `cacheKey` 决定是否重提 |

### 3.4 `fr:notes:*`（6）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:notes:list` | R→M | `NotesListRequest` | `NotesListResponse` | `FR-LIB-005` `FR-NOTE-001` `+C` | 损坏行跳过并计 `unparsableLines`，绝不整体失败 |
| `fr:notes:upsert` | R→M | `NotesUpsertRequest` | `NotesUpsertResponse` | `FR-LIB-005` `FR-NOTE-001` `FR-NOTE-003` `FR-NOTE-004` `FR-STORE-002` `+C` | 标注 `id` 由 renderer 生成（ULID）；`sentenceId` 失效 → `orphan:true` **保留**（02 DM-3）；译文中禁止标注 |
| `fr:notes:delete` | R→M | `NotesDeleteRequest` | `NotesDeleteResponse` | `FR-LIB-005` `FR-NOTE-001` `FR-NOTE-005` `+C` | 默认追加 `deleted:true` 墓碑；`hard` 仅测试/doctor |
| `fr:notes:exportMarkdown` | R→M | `NotesExportMarkdownRequest` | `NotesExportMarkdownResponse` | `FR-LIB-005` `FR-NOTE-001` `FR-STORE-001` `FR-STORE-002` `+C` | `saveTo:'dialog'` 由主进程弹保存框；只回 `fileName`，**不回绝对路径** |
| `fr:notes:importMarkdown` | R→M | `NotesImportMarkdownRequest` | `NotesImportMarkdownResponse` | `FR-LIB-005` `FR-NOTE-001` `FR-NOTE-003` `+C` | front-matter 必须含 `docId` 与锚点；`merge` 冲突保留本地并列 `conflicts[]` |
| `fr:notes:updateProgress` | R→M | `NotesUpdateProgressRequest` | `NotesUpdateProgressResponse` | `FR-LIB-005` `FR-NOTE-003` `FR-STORE-002` `+C` | 阅读位置（含 `translationMode`）；`clientEventId` 幂等；节流 ≤ 1 s |

### 3.5 `fr:translate:*`（9）+ 1 事件

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:translate:translateUnits` | R→M | `TranslateUnitsRequest` | `TranslateUnitsResponse` | `FR-LIB-005` `FR-TRANS-001` `FR-TRANS-002` `FR-TRANS-003` `FR-TRANS-004` `FR-TRANS-005` `FR-TRANS-006` `FR-TRANS-007` `FR-TRANS-008` `FR-TRANS-009` `FR-TRANS-010` `FR-TRANS-011` `FR-TRANS-012` `FR-TRANS-013` `FR-TRANS-015` `FR-TRANS-016` `FR-TRANS-017` `FR-NET-003` `+C` | `source` 为可辨识联合：`document` 分支由主进程解析原文，`selection` 分支翻译划词；批字符超 `TRANSLATE_BATCH_CHARS(4000)` → `FR-TRANS-008`；用户取消 → `FR-TRANS-011`；术语强制替换断言未过 → `FR-TRANS-013`（P0） |
| `fr:translate:cancel` | R→M | `TranslateCancelRequest` | `TranslateCancelResponse` | `+C` | 已结束 → `canceled:false`（不算错误） |
| `fr:translate:getCache` | R→M | `TranslateGetCacheRequest` | `TranslateGetCacheResponse` | `FR-LIB-005` `FR-TRANS-015` `FR-STORE-004` `+C` | 返回 `sourceHash`/`cacheKey` 供 UI 显示"已缓存/已过期"；缓存损坏 → `FR-TRANS-015`（自动重建 + warn） |
| `fr:translate:clearCache` | R→M | `TranslateClearCacheRequest` | `TranslateClearCacheResponse` | `FR-STORE-002` `FR-STORE-007` `+C` | 绝不影响 `paper.pdf`/`blocks.json`/笔记 |
| `fr:translate:listProviders` | R→M | `TranslateListProvidersRequest` | `TranslateListProvidersResponse` | `+C` | 返回 `order` 与 `activeProviderId`；**只回 host，绝不回密钥** |
| `fr:translate:testProvider` | R→M | `TranslateTestProviderRequest` | `TranslateTestProviderResponse` | `FR-TRANS-001` `FR-TRANS-002` `FR-TRANS-004` `FR-TRANS-010` `FR-NET-002` `FR-NET-003` `+C` | 固定短句探测，**不发送文档内容** |
| `fr:translate:listGlossary` | R→M | `TranslateListGlossaryRequest` | `TranslateListGlossaryResponse` | `FR-LIB-005` `+C` | `scope` 决定读 `library/<citekey>/glossary.csv` 或共享表 |
| `fr:translate:upsertGlossary` | R→M | `TranslateUpsertGlossaryRequest` | `TranslateUpsertGlossaryResponse` | `FR-LIB-005` `FR-TRANS-007` `FR-TRANS-014` `FR-STORE-002` `+C` | 去重键 = `caseSensitive ? source : source.toLocaleLowerCase('en-US')`；冲突保留先出现者；导入行非法（缺列/坏 `caseSensitive`/非 UTF-8）→ `FR-TRANS-014`，报文含行号 |
| `fr:translate:deleteGlossary` | R→M | `TranslateDeleteGlossaryRequest` | `TranslateDeleteGlossaryResponse` | `FR-LIB-005` `FR-STORE-002` `+C` | 按 `source` 批量删除 |
| `fr:translate:progress` | M→R | `TranslateProgressEvent` | — | — | 每批完成必发；`state` 终态时必发 |

### 3.6 `fr:fetch:*`（4）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:fetch:resolveMetadata` | R→M | `FetchResolveMetadataRequest` | `FetchResolveMetadataResponse` | `FR-FETCH-002` `FR-FETCH-003` `FR-FETCH-004` `FR-NET-001` `FR-NET-002` `FR-NET-003` `+C` | DOI 正则前置校验（`FR-FETCH-003`）；只经 Crossref/OpenAlex |
| `fr:fetch:fetchOpenAccess` | R→M | `FetchOpenAccessRequest` | `FetchOpenAccessResponse` | `FR-LIB-001` `FR-LIB-002` `FR-LIB-005` `FR-FETCH-001` `FR-FETCH-002` `FR-NET-001` `FR-NET-002` `FR-NET-003` `+C` | 无 OA → `outcome='needs-user-session'`（**不是** 绕过）；只回 `landingHost` |
| `fr:fetch:listProviders` | R→M | `FetchListProvidersRequest` | `FetchListProvidersResponse` | `+C` | 返回域名清单与 `sourceKind` 映射，供 UI 解释"会访问哪些站" |
| `fr:fetch:auditLog` | R→M | `FetchAuditLogRequest` | `FetchAuditLogResponse` | `+C` | 字段与 `09-fetch-compliance.md` §6 的 `net-audit.jsonl` 一一对应（`at/provider/host/status/bytes/purpose/method/path/redirects/policy/reason`）；`policy='deny'` 的条目必留 |

### 3.7 `fr:zotero:*`（4）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:zotero:detect` | R→M | `ZoteroDetectRequest` | `ZoteroDetectResponse` | `+C` | 找不到 → `found:false`（非错误）；`writable` 恒 `false` |
| `fr:zotero:listCollections` | R→M | `ZoteroListCollectionsRequest` | `ZoteroListCollectionsResponse` | `FR-LIB-005` `FR-LIB-009` `FR-STORE-002` `FR-STORE-004` `+C` | 基于只读副本；库被 Zotero 独占 → `FR-LIB-009` |
| `fr:zotero:importSelection` | R→M | `ZoteroImportSelectionRequest` | `ZoteroImportSelectionResponse` | `FR-LIB-005` `FR-LIB-009` `FR-STORE-002` `+C` | 两个 key 列表至少一个；空选择 → `FR-IPC-002`(`reason=empty_selection`)；**逐条目容错**：单条问题进 `failures[]`；`warn:` `FR-LIB-003` |
| `fr:zotero:status` | R→M | `ZoteroStatusRequest` | `ZoteroStatusResponse` | `+C` | `wroteUserLibrary` 恒 `false`（只读保证） |

### 3.8 `fr:app:*`（11）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:app:getConfig` | R→M | `AppGetConfigRequest` | `AppGetConfigResponse` | `+C` | **永不失败**：配置损坏 → 返回默认值 + `restoredFromBackup:true` + `warn:` `FR-STORE-008`（不阻断启动） |
| `fr:app:setConfig` | R→M | `AppSetConfigRequest` | `AppSetConfigResponse` | `FR-STORE-002` `FR-STORE-008` `+C` | 未知 key → `FR-IPC-002`；取值越界/`expectRevision` 不符 → `FR-STORE-008` |
| `fr:app:getVersion` | R→M | `AppGetVersionRequest` | `AppGetVersionResponse` | `+C` | 用于问题报告与 `/doctor` |
| `fr:app:checkUpdate` | R→M | `AppCheckUpdateRequest` | `AppCheckUpdateResponse` | `FR-NET-001` `FR-NET-002` `FR-NET-005` `+C` | 失败降级为 `status:'error'`；只提示不自动安装；更新走签名更新源（`12-build-release.md`），不经 NetGuard 白名单，故不返回 `FR-NET-003` |
| `fr:app:openExternal` | R→M | `AppOpenExternalRequest` | `AppOpenExternalResponse` | `FR-NET-001` `FR-NET-002` `FR-NET-003` `+C` | **必须**经 NetGuard（§5.3）；仅 `https`；非 `user-click` 需命中白名单；`user-click` 未确认 → `FR-NET-003` |
| `fr:app:exportLogs` | R→M | `AppExportLogsRequest` | `AppExportLogsResponse` | `FR-STORE-001` `FR-STORE-002` `+C` | 强制 `Redactor`（11 §6.2）；只回 `fileName` |
| `fr:app:getCacheInfo` | R→M | `AppGetCacheInfoRequest` | `AppGetCacheInfoResponse` | `FR-STORE-007` `+C` | `maxBytes` 默认 `CACHE_MAX_MB = 500 MB` |
| `fr:app:clearCache` | R→M | `AppClearCacheRequest` | `AppClearCacheResponse` | `FR-STORE-002` `FR-STORE-007` `+C` | 按类别清理；失败类别进 `failedKinds[]` |
| `fr:app:doctor` | R→M | `AppDoctorRequest` | `AppDoctorResponse` | `FR-STORE-002` `FR-STORE-004` `+C` | 应用内等价 `freeread doctor` 子命令（05 §9）；问题进 `checks[]`，不抛错 |
| `fr:app:getCapabilities` | R→M | `AppGetCapabilitiesRequest` | `AppGetCapabilitiesResponse` | `+C` | 见 §6；`quickMode === (engine === 'rule')` |
| `fr:app:getApiVersion` | R→M | `AppGetApiVersionRequest` | `AppGetApiVersionResponse` | `+C` | 启动握手，见 §7 |

### 3.9 `fr:window:*`（3）

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:window:openReaderTab` | R→M | `WindowOpenReaderTabRequest` | `WindowOpenReaderTabResponse` | `FR-LIB-005` `+C` | V1：每个 `BrowserWindow` 仅承载 1 个文档视图（07 §R-4）；同 `docId` 已开 → `reused:true` 并聚焦（不新增，故无"超出上限"错误） |
| `fr:window:closeTab` | R→M | `WindowCloseTabRequest` | `WindowCloseTabResponse` | `+C` | 关闭前同步落盘阅读位置；未知 `tabId` → `FR-IPC-002` |
| `fr:window:focusMain` | R→M | `WindowFocusMainRequest` | `WindowFocusMainResponse` | `+C` | 托盘/通知/外链返回 |

### 3.10 `fr:agent:*`（10）+ 1 事件

> 权威定义见 [`14-agent.md`](14-agent.md)（工具/权限/事件流/预算）；表中类型名对应 manifest `$defs`，会话事件用 `agent-session.schema.json`，权限表用 `agent-permissions.schema.json`。

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:agent:start` | R→M | `AgentStartRequest` | `AgentStartResponse` | `FR-AGT-012` `FR-STORE-002` `FR-STORE-012` `+C` | 创建会话（`projectId?`/`title?` 均可省略）；**未配置 LLM Provider 不算失败**：建会话可完成 → `ok:true` + `llmReady:false` + `activeProviderId:null`，UI 显示引导（14 §10.2）；`FR-AGT-001` 在真正发起（`send`）时才返回，故**不**出现在本通道 errors[] |
| `fr:agent:send` | R→M | `AgentSendRequest` | `AgentSendResponse` | `FR-AGT-001` `FR-AGT-012` `FR-STORE-002` `+C` | 受理即返回 `{runId}`（`state:'planning'`），过程全部走事件流；无可用 Provider → `ok:false` + `FR-AGT-001`（warn 级但**操作无法完成**，同 `FR-FETCH-001` 先例；消息不入库）；`attachments[].ref` 只允许「文献库 `docId`」或「工作区相对路径」（§5.2 **A5**），绝对路径 → `FR-IPC-002`(`reason=absolute_ref_forbidden`)；同项目已有活动 run → `FR-IPC-002`(`reason=run_in_progress`，AG-1)；`clientEventId` 幂等 → `deduped:true` |
| `fr:agent:cancel` | R→M | `AgentCancelRequest` | `AgentCancelResponse` | `+C` | 已终态 → `canceled:false`（不算错误）；`canceled:true` 时 run 以 `FR-AGT-007`（warn）结束并经 `run_state`/`error` 事件回推；**已产出内容保留**（消息/工具结果/笔记）；未知 `sessionId` → `FR-IPC-002`(`reason=unknown_reference`) |
| `fr:agent:listSessions` | R→M | `AgentListSessionsRequest` | `AgentListSessionsResponse` | `+C` | 强制分页（`offset`/`limit` 必填，`limit ≤ 100`）；摘要**不含**笔记/译文全文与绝对路径（AG-8） |
| `fr:agent:getSession` | R→M | `AgentGetSessionRequest` | `AgentGetSessionResponse` | `FR-AGT-010` `FR-STORE-002` `+C` | 会话元信息 + 事件流；`afterSeq` 增量（0/省略 = 全量），`limit ≤ 500`，`hasMore`/`lastSeq` 驱动续拉；**部分损坏**行跳过并计 `unparsableLines`（`> 0` 时记 `FR-AGT-010` 到 `op_log` + UI 提示，但响应仍 `ok:true`，**不**用 `ok:false` 表达降级）；仅当文件整体不可读/完全不可解析才 `ok:false` + `FR-AGT-010` |
| `fr:agent:deleteSession` | R→M | `AgentDeleteSessionRequest` | `AgentDeleteSessionResponse` | `FR-STORE-002` `FR-STORE-012` `+C` | 立即删除会话文件与事件流；`auditKept` 恒 `true` —— `op_log` 的 `agent.tool` 审计行按 11 §3 保留策略留存（AG-2） |
| `fr:agent:listTools` | R→M | `AgentListToolsRequest` | `AgentListToolsResponse` | `FR-AGT-012` `+C` | 工具清单（**V1 恒 14 个**，含 `inputSchema`/`sideEffect`/`defaultRule`/`timeoutMs`）+ 项目权限表 + Provider 能力；契约测试必须断言数量与名称与代码内工具表一致（14 §14）；只回 `endpointHost`，**绝不回密钥** |
| `fr:agent:setPermissionRule` | R→M | `AgentSetPermissionRuleRequest` | `AgentSetPermissionRuleResponse` | `FR-AGT-012` `FR-STORE-002` `FR-STORE-012` `+C` | 写 `permissions.json` 并必写审计；`rule:'deny'` 为项目内终态（AG-9，后续调用直接 `FR-AGT-003`），**只能由本通道**显式改回 `ask`/`always`/`once`；工具名不在清单内 → `FR-IPC-002`(`reason=unknown_tool`) |
| `fr:agent:listSkills` | R→M | `AgentListSkillsRequest` | `AgentListSkillsResponse` | `FR-AGT-012` `+C` | 每项含 `valid`/`reason`；`valid:false` 的技能**不得注入上下文** |
| `fr:agent:installSkill` | R→M | `AgentInstallSkillRequest` | `AgentInstallSkillResponse` | `FR-AGT-009` `FR-AGT-012` `FR-STORE-001` `FR-STORE-002` `+C` | **仅本地目录**（V1 无远端下载/技能市场）；`sourceDir` 经 `assertUserPath(kind:'dir')`；front-matter/许可清单/包内路径穿越/文件数 ≤ 200/总体积 ≤ 20 MiB 任一不合格 → `FR-AGT-009`（含同名未传 `overwrite:true`）；`scriptsIgnored` 恒 `true`（V1 不执行技能脚本） |
| `fr:agent:event` | M→R | `AgentEventPayload` | — | — | 载荷 `{sessionId, seq, kind, payload}`，`kind ∈ {message,tool_start,tool_end,permission_required,run_state,error}`；`permission_required` 的 `payload.timeoutMs` 默认 `120000`（超时按 `deny`，仅本次 run，回灌模型时用 `FR-AGT-003`）；`error` 的 `payload.code` 取 `FR-AGT-002/004/005/006/007/008/010/011`；`run_state` 的 `payload.verified:false` 时 UI 必须标注「未经验证」（AG-10）；**外层信封 `seq` ≠ 载荷内 `seq`**（§2.3） |

### 3.11 `fr:project:*`（5）+ 1 事件

> 目录布局、清理与导出范围冻结于 [`14-agent.md §7`](14-agent.md)；`projectId` 为 ULID，renderer **永不**传项目路径。

| 通道 | 方向 | 载荷 | 返回 | 失败错误码 | 备注 |
|---|---|---|---|---|---|
| `fr:project:ensure` | R→M | `ProjectEnsureRequest` | `ProjectEnsureResponse` | `FR-AGT-012` `FR-STORE-001` `FR-STORE-002` `+C` | `projectId` 与 `title` **恰好一个**（都缺或都给 → `FR-IPC-002`）；目录树（`project.json`/`permissions.json`/`skills/`/`workspace/`/`sessions/`）只由主进程创建；`workspaceReady:false` → UI 必须禁用发送（`FR-AGT-012`）并给「更换/修复项目目录」入口 |
| `fr:project:getPermissions` | R→M | `ProjectGetPermissionsRequest` | `ProjectGetPermissionsResponse` | `FR-AGT-012` `FR-STORE-002` `+C` | 读 `permissions.json`；文件缺失/不合 schema → 用各工具 `defaultRule` 重建 + `restoredFromDefaults:true` + `warn:` `FR-STORE-008`（与 `config.json` 同属「配置非法→恢复默认」语义），**不阻断** |
| `fr:project:listFiles` | R→M | `ProjectListFilesRequest` | `ProjectListFilesResponse` | `FR-AGT-012` `+C` | 强制分页（`limit ≤ 2000`）；只回工作区相对路径（**返回值禁止绝对路径**，05 §11 PR1）；`dir` 经 §5.2 `assertWorkspaceRelPath` + `assertContainedPath` 双重校验，越界 → `FR-IPC-002`(`reason=outside_root`) |
| `fr:project:importFiles` | R→M | `ProjectImportFilesRequest` | `ProjectImportFilesResponse` | `FR-AGT-012` `FR-STORE-001` `FR-STORE-002` `+C` | `sourcePaths[]` 为用户经对话框/拖放选择的本地文件（≤ 200），逐个 `assertUserPath(kind:'file')`；**逐文件容错**：单文件问题进 `failures[]`（`code` 取自 11 §3，如 `FR-STORE-019` 超 `MAX_WORKSPACE_FILE_BYTES`），仅工作区根不可写才 `ok:false`；响应只回相对路径 + 文件名 |
| `fr:project:exportZip` | R→M | `ProjectExportZipRequest` | `ProjectExportZipResponse` | `FR-AGT-012` `FR-STORE-001` `FR-STORE-002` `+C` | 落盘位置只由系统保存对话框决定（§5.2 **A3**），只回 `fileName`；zip 恒含 `project.json`+`workspace/`+`skills/`，**恒不含** `permissions.json` 与 `sessions/`（`excluded` 字段回执，14 §7）；用户取消 → `saved:false`（非错误） |
| `fr:project:changed` | M→R | `ProjectChangedEvent` | — | — | 载荷最小集 `{projectId}`（14 §11），`action`/`at` 为可选扩展；仅失效缓存，非真源 |

### 3.12 事件表（8）

| 事件 | 方向 | 载荷 | 触发 | 备注 |
|---|---|---|---|---|
| `fr:parser:progress` | M→R | `ParseProgressEvent` | 每页/每 50 页批完成，或状态跃迁 | 节流 ≥ 100 ms；`progress` 保留 3 位小数 |
| `fr:parser:failed` | M→R | `ParserFailedEvent` | `state=failed` | 含 `error` 与 `fallbackChain`；不自动重放 |
| `fr:translate:progress` | M→R | `TranslateProgressEvent` | 每批完成 / 终态 | `docId` 为 `null` 表示划词（不落盘） |
| `fr:library:changed` | M→R | `LibraryChangedEvent` | 导入/移除/改名/元数据/重建索引，或外部文件变更 | `origin` 区分应用内与外部变更 |
| `fr:notes:changed` | M→R | `NotesChangedEvent` | 标注增删改、导入、阅读位置写入 | 对应 02 的 `AnnotationChanged` 与进度写入 |
| `fr:app:updateAvailable` | M→R | `UpdateAvailableEvent` | 后台检查发现新版本 | 只提示；安装须用户显式操作 |
| `fr:agent:event` | M→R | `AgentEventPayload` | run 状态跃迁、消息增量、工具开始/结束、权限询问、run 级错误 | 只追加可回放（AG-7）；`seq` 为会话内序号，渲染端跳号后必须用 `fr:agent:getSession` 的 `afterSeq` 补齐；`error` 的 `code` 取 `FR-AGT-002/004/005/006/007/008/010/011` |
| `fr:project:changed` | M→R | `ProjectChangedEvent` | 项目元信息、工作区文件、权限表或技能变更 | 仅失效缓存；状态须可由 `fr:project:*` 重新查询 |

---

## 4. 载荷契约与完整示例

字段级权威定义在 manifest `$defs`。以下 13 个关键通道给出完整请求/响应示例（可直接作为契约测试夹具）。

### 4.1 `fr:library:import`

```jsonc
// 请求（本地文件）
{ "source": { "kind": "file", "path": "D:\\papers\\attention.pdf" },
  "citekey": "smith2020-attention", "tags": ["nlp"], "dryRun": false }
// 请求（白名单 URL：必须 https，且 host 命中 NetGuard 白名单，否则 FR-NET-003）
{ "source": { "kind": "url", "url": "https://arxiv.org/pdf/1706.03762" } }
// 响应
{ "ok": true, "data": { "docId": "9f2c…cdef", "citekey": "smith2020-attention",
  "created": true, "deduped": false, "pageCount": 15,
  "meta": { "schemaVersion": 1, "citekey": "smith2020-attention", "docId": "9f2c…cdef",
            "title": "attention", "authors": [], "tags": ["nlp"], "collections": [],
            "addedAt": "2026-10-03T00:12:00Z", "updatedAt": "2026-10-03T00:12:00Z",
            "source": { "kind": "local-file" } },
  "warnings": ["FR-LIB-003"] } }   // warn: 文件超过 MAX_FILE_SIZE_MB，仍已导入
```

### 4.2 `fr:doc:open`

```jsonc
// 请求（01-architecture.md §启动时序的 citekey 形式；mode 省略则取 config.reader.defaultMode）
{ "citekey": "smith2020-attention" }
// 响应
{ "ok": true, "data": { "sessionId": "ses_01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "docId": "9f2c…cdef", "citekey": "smith2020-attention", "mode": "reflow",
  "pageCount": 15, "engine": "docling", "anchorReady": true,
  "pdfUrl": "fr-file://9f2c…cdef/paper.pdf",
  "restored": { "page": 3, "sentenceId": "s_b_3_7_2", "mode": "reflow",
                "scrollRatio": 0.38, "degraded": false } } }
```

### 4.3 `fr:doc:getAnchorModel`

```jsonc
// 请求
{ "docId": "9f2c…cdef", "sessionId": "ses_01J8ZQ4K7M9P2V4X6B8N0Q3T5R" }
// 响应（model 段为节选，仍通过 doc-anchor-model.schema.json 校验）
{ "ok": true, "data": { "docId": "9f2c…cdef", "source": "cache",
  "cacheKey": "b7d1…9a3f",
  "model": { "schemaVersion": 1, "docId": "9f2c…cdef",
    "engine": { "name": "docling", "version": "2.5.1" },
    "pageSize": { "3": { "w": 595.276, "h": 841.89 } },
    "blocks": [ { "id": "b_3_7", "page": 3, "rect": { "x": 72.1, "y": 301.4, "w": 210.3, "h": 11.8 },
                  "type": "text", "score": 0.93, "order": 41, "text": "The encoder stacks six layers." } ],
    "paragraphs": [ { "id": "pa_3_4", "blockIds": ["b_3_7"], "sentenceIds": ["s_b_3_7_1"] } ],
    "sentences": [ { "id": "s_b_3_7_1", "blockId": "b_3_7", "page": 3,
                     "text": "The encoder stacks six layers.", "kind": "text",
                     "lines": [ { "lineId": 15, "page": 3, "begin": 0, "len": 31 } ] } ],
    "outline": [], "figures": [], "references": [],
    "stats": { "blockCount": 1, "sentenceCount": 1, "lowConfidenceBlocks": 0, "durationMs": 4120 } } } }
```

### 4.4 `fr:notes:upsert`

```jsonc
// 请求（annotation 结构与 annotation.schema.json 完全一致；id 由 renderer 生成）
{ "docId": "9f2c…cdef", "sessionId": "ses_01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "annotation": { "schemaVersion": 1, "id": "an_01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
    "docId": "9f2c…cdef", "kind": "highlight", "color": "yellow",
    "quote": "The encoder stacks six layers.",
    "anchor": { "page": 3, "blockId": "b_3_7", "sentenceId": "s_b_3_7_1",
                "rects": [ { "x": 72.1, "y": 301.4, "w": 210.3, "h": 11.8 } ],
                "lines": [ { "lineId": 15, "page": 3, "begin": 0, "len": 31 } ] },
    "createdAt": "2026-10-03T00:20:11Z", "deviceId": "dev_01J8ZQ4K7M9P2V4X6B8N0Q3T5R" } }
// 响应
{ "ok": true, "data": { "docId": "9f2c…cdef",
  "annotationId": "an_01J8ZQ4K7M9P2V4X6B8N0Q3T5R", "created": true, "orphan": false } }
```

### 4.5 `fr:translate:translateUnits`

```jsonc
// 请求（document 分支：原文由主进程从 blocks.json 解析，renderer 不传文本）
{ "requestId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R", "lang": "zh-CN", "useCache": true,
  "source": { "kind": "document", "docId": "9f2c…cdef", "unitIds": ["pa_3_4", "s_b_3_7_1"] } }
// 请求（selection 分支：划词；docId 不在载荷中，故不落翻译缓存文件）
{ "requestId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5S", "lang": "zh-CN", "useCache": true,
  "source": { "kind": "selection", "text": "in vitro",
              "context": { "docTitle": "Attention Is All You Need", "field": "biology" } } }
// 响应（results[].ref：document 分支 = unitId，selection 分支 = sel_<序号>）
{ "ok": true, "data": { "requestId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "providerId": "ollama", "modelId": "qwen2.5:7b-instruct", "from": "en", "to": "zh-CN",
  "glossaryHash": "3c9f…12ab",
  "results": [ { "ref": "pa_3_4", "target": "编码器堆叠了六层。", "cached": true,
                 "sourceHash": "aa11…00ff", "cacheKey": "7e2b…91c4", "providerId": "ollama" } ],
  "stats": { "requested": 2, "cached": 1, "translated": 1, "totalChars": 412 } } }
```

### 4.6 `fr:fetch:fetchOpenAccess`

```jsonc
// 请求
{ "docId": "9f2c…cdef", "doi": "10.1109/TIT.2020.1234567",
  "preferProviders": ["unpaywall", "arxiv", "pmc"], "allowUserSession": false }
// 响应：拿不到 OA —— 明确返回"需用户会话"，绝不回退任何绕过渠道
{ "ok": true, "data": { "docId": "9f2c…cdef", "outcome": "needs-user-session",
  "provider": "unpaywall", "sourceKind": "unpaywall", "license": null,
  "landingHost": "ieeexplore.ieee.org" } }
// 响应：成功下载（sha256 = 新 docId；不返回绝对路径）
{ "ok": true, "data": { "docId": "9f2c…cdef", "outcome": "downloaded", "provider": "arxiv",
  "sha256": "77aa…be21", "sourceKind": "arxiv", "license": "CC-BY-4.0",
  "landingHost": "arxiv.org" } }
```

### 4.7 `fr:app:openExternal`

```jsonc
// 请求：白名单来源（无需用户确认也可，仍写审计）
{ "url": "https://arxiv.org/abs/1706.03762", "reason": "oa-fulltext", "confirmedByUser": false }
// 请求：用户点击的非白名单链接 —— 必须由 UI 先弹确认
{ "url": "https://example-publisher.org/paper/123", "reason": "user-click", "confirmedByUser": true }
// 响应
{ "ok": true, "data": { "host": "arxiv.org", "opened": true, "whitelisted": true } }
// 失败：非白名单且非用户确认
{ "ok": false, "error": { "code": "FR-NET-003", "message": "host not in NetGuard allowlist",
  "category": "compliance", "severity": "fatal", "retryable": false,
  "i18nKey": "errors.FR-NET-003", "details": { "host": "cdn.example.net" } } }
```

> **`Patch.pageFingerprint` 算法（冻结）**：取 `ops[].blockId` 涉及页面的全部 `Sentence`，按 `id` 升序排列为 `[[id, text], …]`，用键序固定的 canonical JSON（无空白）序列化后取 sha256 hex。`fr:doc:applyPatch` 比对不一致 → `FR-ANCHOR-012`（patch 过期，拒绝应用）。

### 4.8 `fr:agent:send`

```jsonc
// 请求：附件只有两种合法形态 —— 文献库 docId（kind='doc'）或工作区相对路径（kind='workspace'）
{ "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "text": "把这三篇里关于注意力稀疏化的结论整理进 workspace/summary.md，并给出每条结论的工具引用。",
  "attachments": [ { "kind": "doc", "docId": "9f2c…cdef" },
                   { "kind": "workspace", "path": "inbox/notes.md", "note": "上次的提纲" } ],
  "clientEventId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5S" }
// 响应：受理即返回（run 在后台推进，过程全部走 fr:agent:event）
{ "ok": true, "data": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "runId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5T", "state": "planning",
  "queuedAt": 1759449600123, "deduped": false } }
// 事件（节选）：工具执行前的权限询问；外层信封 seq 与会话事件 seq 语义不同（§2.3）
{ "type": "fr:agent:event", "ts": 1759449601200, "seq": 12,
  "payload": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R", "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V",
    "runId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5T", "seq": 7, "kind": "permission_required",
    "payload": { "callId": "call_7Qk2M4p1", "tool": "workspace_write", "risk": "write",
                 "argsSummary": "write workspace/summary.md (4.1 KiB)", "timeoutMs": 120000 } } }
// 失败：无可用 LLM Provider —— 属「无法受理」（FR-AGT-001 为 warn 级，同 FR-FETCH-001 先例；消息不入库、不建 run）
{ "ok": false, "error": { "code": "FR-AGT-001", "message": "no LLM provider is available",
  "category": "provider", "severity": "warn", "retryable": false,
  "i18nKey": "errors.FR-AGT-001", "details": { "reason": "provider_unavailable" } } }
// 失败：项目工作区不可用（被移动 / 无权限）
{ "ok": false, "error": { "code": "FR-AGT-012", "message": "project workspace is not writable",
  "category": "storage", "severity": "error", "retryable": true,
  "i18nKey": "errors.FR-AGT-012", "details": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V" } } }
// 失败：附件写了绝对路径（禁止），或同一项目已有活动 run（AG-1）
{ "ok": false, "error": { "code": "FR-IPC-002",
  "message": "attachment ref must be a library docId or a workspace-relative path",
  "category": "ipc", "severity": "error", "retryable": false,
  "i18nKey": "errors.FR-IPC-002", "details": { "reason": "absolute_ref_forbidden" } } }
```

### 4.9 `fr:agent:start`

```jsonc
// 请求：两字段都可省略（省略 projectId → 主进程 ensure 默认项目；省略 title → 按首条消息生成）
{ "title": "注意力稀疏化综述" }
// 响应：未配置 LLM Provider —— 不是错误：建会话可完成，故 ok:true + llmReady:false（UI 显示配置引导，14-agent.md §10.2）
{ "ok": true, "data": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "title": "注意力稀疏化综述",
  "createdAt": 1759449600123, "llmReady": false, "activeProviderId": null,
  "modelId": null, "warnings": [] } }
// 响应：本地 Ollama 与模型均就绪
{ "ok": true, "data": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5S",
  "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "title": "注意力稀疏化综述",
  "createdAt": 1759449600456, "llmReady": true, "activeProviderId": "ollama",
  "modelId": "qwen2.5:7b-instruct", "warnings": [] } }
// 失败：项目目录不可写 / 磁盘不足 / 原子写失败
{ "ok": false, "error": { "code": "FR-STORE-002", "message": "no write permission on projects dir",
  "category": "storage", "severity": "fatal", "retryable": false,
  "i18nKey": "errors.FR-STORE-002", "details": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V" } } }
```

### 4.10 `fr:agent:getSession`

```jsonc
// 请求：afterSeq 增量拉取（0/省略 = 全量）；断线重连必须带最后一次收到的会话 seq
{ "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R", "afterSeq": 6, "limit": 200 }
// 响应：events[] 每行都通过 agent-session.schema.json 校验（AG-7 append-only，可完整回放）
{ "ok": true, "data": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R",
  "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "title": "注意力稀疏化综述",
  "createdAt": 1759449600123, "updatedAt": 1759449660456,
  "run": { "runId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5T", "state": "finished", "startedAt": 1759449600200,
           "steps": 5, "toolCalls": 7, "reason": null },
  "events": [
    { "type": "tool_result", "seq": 7, "at": 1759449602000, "callId": "call_7Qk2M4p1", "ok": true,
      "summary": "search_library: 3 hits for \"sparse attention\"", "durationMs": 412 },
    { "type": "run", "seq": 8, "at": 1759449660456, "runId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5T",
      "state": "finished", "steps": 5, "toolCalls": 7,
      "citations": [ { "callId": "call_7Qk2M4p1", "docId": "9f2c…cdef", "note": "§3.2 结论" } ] } ],
  "lastSeq": 8, "hasMore": false, "unparsableLines": 0, "warnings": [] } }
// 失败：会话文件不可读（IO/权限）
{ "ok": false, "error": { "code": "FR-STORE-002", "message": "cannot read session file",
  "category": "storage", "severity": "fatal", "retryable": false,
  "i18nKey": "errors.FR-STORE-002", "details": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R" } } }
// 失败：会话文件整体损坏（不可解析）—— 部分损坏不在此列（跳过并计 unparsableLines，仍 ok:true）
{ "ok": false, "error": { "code": "FR-AGT-010", "message": "session stream is not parsable",
  "category": "storage", "severity": "error", "retryable": true,
  "i18nKey": "errors.FR-AGT-010", "details": { "sessionId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5R", "unparsableLines": 14 } } }
```

### 4.11 `fr:agent:setPermissionRule`

```jsonc
// 请求：把写工作区设为「总是允许」（高风险，UI 必须先二次确认并显示风险等级）
{ "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "tool": "workspace_write", "rule": "always" }
// 响应：回写盘后的完整权限表（真源 projects/<projectId>/permissions.json）
{ "ok": true, "data": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V",
  "tool": "workspace_write", "rule": "always", "updatedAt": 1759449700000, "effective": "allow",
  "permissions": { "schemaVersion": 1, "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V",
    "rules": [ { "tool": "workspace_write", "rule": "always", "updatedAt": 1759449700000 },
               { "tool": "run_python", "rule": "deny", "updatedAt": 1759448000000 } ] } } }
// 失败：工具名不在 V1 的 14 个工具内（不得凭 UI 传入任意字符串）
{ "ok": false, "error": { "code": "FR-IPC-002", "message": "unknown tool",
  "category": "ipc", "severity": "error", "retryable": false,
  "i18nKey": "errors.FR-IPC-002", "details": { "reason": "unknown_tool", "tool": "browse_web" } } }
// 语义：rule='deny' 后该工具在本项目内直接以 FR-AGT-003 返回且**不再询问**（AG-9）；
//       解除 deny 只能再次调用本通道显式改回 ask/always/once（必写审计 op_log）
```

### 4.12 `fr:project:importFiles`

```jsonc
// 请求：用户经系统对话框选中的三个本地文件 → 导入工作区 inbox/2026/
{ "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V",
  "sourcePaths": ["D:\\notes\\draft.md", "D:\\notes\\table.csv", "D:\\notes\\dataset.bin"],
  "destDir": "inbox/2026", "overwrite": false }
// 响应：逐文件容错 —— 整批 ok:true：1 个写入、1 个同名跳过（overwrite:false）、1 个超体积失败
{ "ok": true, "data": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V",
  "imported": 1, "skipped": 1, "failed": 1,
  "files": ["inbox/2026/draft.md"], "skippedFiles": ["table.csv"],
  "failures": [ { "fileName": "dataset.bin", "code": "FR-STORE-019" } ],
  "warnings": [] } }
// 失败：工作区根不可写（仅此情形整批失败）
{ "ok": false, "error": { "code": "FR-STORE-002", "message": "workspace is not writable",
  "category": "storage", "severity": "fatal", "retryable": false,
  "i18nKey": "errors.FR-STORE-002", "details": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V" } } }
// 失败：源路径非法（.. / UNC / 符号链接 / 应用内部路径 / 库内目录）
{ "ok": false, "error": { "code": "FR-IPC-002", "message": "source path is not an allowed user file",
  "category": "ipc", "severity": "error", "retryable": false,
  "i18nKey": "errors.FR-IPC-002", "details": { "reason": "dotdot_segment" } } }
```

### 4.13 `fr:project:exportZip`

```jsonc
// 请求：落盘位置只由主进程的系统保存对话框决定（renderer 永不提供目标路径，§5.2 A3）
{ "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "saveTo": "dialog" }
// 响应：只回文件名；excluded 回执冻结了「不含 permissions.json 与 sessions/」（14-agent.md §7）
{ "ok": true, "data": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "saved": true,
  "fileName": "attention-survey-20261003.zip", "bytes": 1843200, "entries": 27,
  "excluded": ["permissions.json", "sessions/"], "warnings": [] } }
// 响应：用户在保存对话框取消 —— 不是错误
{ "ok": true, "data": { "projectId": "01J8ZQ4K7M9P2V4X6B8N0Q3T5V", "saved": false,
  "fileName": null, "bytes": 0, "entries": 0,
  "excluded": ["permissions.json", "sessions/"], "warnings": [] } }
```

---

## 5. 安全与校验

### 5.1 主进程侧 zod 严格校验（强制）

```ts
// apps/desktop/src/main/ipc/registry.generated.ts
export const HANDLERS: { [K in FrChannel]: Handler<K> } = { … };
// 每个 handler 的第一步：schema.parse(payload) —— 由 manifest 生成，一律 .strict()
//   · 未知字段 → ZodError → toAppError(e, 'FR-IPC-002')
//   · 类型/枚举/取值域不符 → 同上
//   · 校验失败必须在调用任何 Service 之前发生（禁止"先写后校验"）
```

### 5.2 路径校验（防路径穿越）

```ts
// apps/desktop/src/main/ipc/guards.ts
/** 用户提供的文件/目录路径（导入源）。返回 realpath。 */
export function assertUserPath(raw: string, kind: 'file' | 'dir'): Promise<string>;
/** 库内路径包含性校验：解析后必须位于任一 root 之内。返回 realpath。 */
export function assertContainedPath(raw: string, roots: readonly string[]): Promise<string>;
/** 工作区相对路径（Agent/项目通道唯一合法的文件标识；禁止绝对路径）。返回原值。 */
export function assertWorkspaceRelPath(raw: string, roots: readonly string[]): Promise<string>;
/** citekey 目录名：^[a-z0-9][a-z0-9-]{0,39}$ 且非保留名。 */
export function assertCitekey(raw: string): string;
/** URL 出站校验（唯一入口为 NetGuard）。 */
export function assertNetUrl(raw: string, ctx: NetGuardContext): URL;
```

```text
assertUserPath(raw, kind):
  1. if (!path.isAbsolute(raw))                      → FR-IPC-002 reason=not_absolute
  2. if (raw.includes('\u0000'))                     → FR-IPC-002 reason=nul_byte
  3. if (raw.split(/[\\/]+/).includes('..'))         → FR-IPC-002 reason=dotdot_segment
  4. if (raw.startsWith('\\\\'))                     → FR-IPC-002 reason=unc_forbidden
  5. st = await lstat(raw); if (st.isSymbolicLink()) → FR-IPC-002 reason=symlink_forbidden
  6. real = await realpath(raw)                      # 解析中间目录的符号链接后再判一次
  7. kind==='file' && !isFile(real)                  → FR-IPC-002 reason=not_a_regular_file
     kind==='dir'  && !isDirectory(real)             → FR-IPC-002 reason=not_a_directory
  8. if (isInsideAppInternals(real))                 → FR-IPC-002 reason=app_internal_path
       # appInternals = {<userData>/cache, <userData>/logs, <userData>/index.sqlite,
       #                 <userData>/config.json, <userData>/glossaries, <libraryPath>/.trash}
  9. if (kind==='file' && !/\.(pdf|epub)$/i.test(real)) → FR-LIB-004     # 见 11 §3.1
 10. return real

assertContainedPath(raw, roots):
  1. real = await realpath(raw)                      # 目标尚不存在时：realpath(dirname) + join(basename)
  2. for (root of roots):
       r   = await realpath(root)
       rel = path.relative(r, real)                  # Windows 大小写不敏感由 path.relative 处理
       if (rel === '') return real
       if (rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel)) return real
  3. → FR-IPC-002 reason=outside_root

assertWorkspaceRelPath(raw, roots):
  1. if (raw === '' || raw.length > 512)             → FR-IPC-002 reason=relpath_invalid
  2. if (/^[A-Za-z]:/.test(raw))                     → FR-IPC-002 reason=absolute_ref_forbidden
     if (raw.startsWith('/') || raw.startsWith('\\')) → FR-IPC-002 reason=absolute_ref_forbidden
  3. if (raw.includes('\u0000'))                     → FR-IPC-002 reason=nul_byte
  4. if (raw.includes('\\') || raw.includes(':'))    → FR-IPC-002 reason=backslash_forbidden
  5. if (raw.split('/').includes('..'))              → FR-IPC-002 reason=dotdot_segment
  6. await assertContainedPath(join(workspacePath, raw), roots)   # 步骤 6 是兜底：即使 1–5 被绕过也拦住
  7. return raw                                       # 返回相对路径，绝不返回绝对路径
```

```text
适用范围（P6 + A5 的机检面）：
  · 绝对路径入口仅 5 处：library.import(source.path) / library.importFolder(dirPath) /
    app.setConfig(libraryPath,cachePath) / project.importFiles(sourcePaths[]) /
    agent.installSkill(sourceDir)  → 一律 assertUserPath(kind)
  · fr:project:* 的全部路径字段（listFiles.dir / importFiles.destDir / 响应中的 path）
    一律 assertWorkspaceRelPath(raw, [workspacePath])
  · 一切含路径的 Agent 载荷（工具入参、事件载荷、附件引用）走同一套校验；
    fr:agent:send 的 attachments[].ref 只允许 {kind:'doc',docId} 或 {kind:'workspace',path}
  · 越界 → FR-IPC-002（载荷层）或 FR-AGT-008（工具层：沙箱越界，fatal 且永不重试，11 §3）
```

硬规则：

- **A1** `library/` 之内禁止符号链接；`fr:app:doctor` 的 `symlink.escape` 检查项负责检出并报告。
- **A2** 一切库内文件访问都由 `docId` → `citekey` → 固定文件名（`paper.pdf`/`meta.json`/`blocks.json`/`notes.md`/`annotations.jsonl`）推导，**renderer 永不提供库内相对路径**。
- **A3** 导出类通道（`fr:notes:exportMarkdown`、`fr:app:exportLogs`、`fr:project:exportZip`）不接收路径参数，落盘位置只由主进程的系统保存对话框决定。
- **A4** 返回值与事件载荷中**不得出现绝对路径**（05 §11 PR1）；自定义协议 `fr-file://<docId>/paper.pdf` 与 `fr-cache://pages/…` 的 handler 必须复用同一套 `assertContainedPath`。
- **A5** Agent 的文件面只有三处（AG-3）：文献库（只读，按 `docId`）、项目 `workspace/`（读写，按 `WorkspaceRelPath`）、NetGuard 白名单（网络）。`fr:agent:send` 的 `attachments[].ref` **只允许**「文献库 `docId`」或「工作区相对路径」；出现绝对路径/盘符/UNC/`..` → `FR-IPC-002`（`reason=absolute_ref_forbidden`/`dotdot_segment`），**禁止**降级为「按原样读取」。

### 5.3 NetGuard（出站唯一入口）

| 规则 | 内容 |
|---|---|
| N1 | 任何 URL 参数（`fr:app:openExternal`、`fr:library:import` 的 url 源）与一切内部出站请求都必须经 `NetGuard.request()` / `assertAllowed()`；绕过即 **F2** |
| N2 | 仅允许 `https:`；`http:` 只允许 `ctx.allowLocal === true` 且 host ∈ {`127.0.0.1`, `::1`, `localhost`}（本地 Ollama / 本地 vLLM）；其余 `http` 与 `file:`/`data:`/`javascript:`/`blob:` 一律 `FR-NET-002`（`reason=scheme_forbidden`，09 §2.4–§2.5） |
| N3 | `fr:app:openExternal` 的 `reason != 'user-click'` 时 host 必须命中白名单；`user-click` + `confirmedByUser:true` 可放行任意 https host，但**必须先弹确认框**、**必写审计**并回 `whitelisted:false`；未确认 → `FR-NET-003`（`reason=user_click_unconfirmed`）。**黑名单优先级最高**（09 §2.3 规则 9 + §3.1），命中即 `reason=denylist` |
| N4 | 白名单域名、`NetPurpose` 取值、审计字段与保留策略以 [`09-fetch-compliance.md`](./09-fetch-compliance.md) §2.1/§2.2/§6 为准；本文只冻结 IPC 侧形状（`purpose ∈ {oa-metadata, oa-fulltext, llm, asset, user-browser}`） |
| N5 | 重定向每跳重新校验、**最多 3 跳**（超限 → `FR-NET-003`）；跨 host 视为新请求重新过白名单；DNS 解析到私网/回环/链路本地地址一律拒绝（SSRF 防护，09 §2.4） |
| N6 | 合规拦截（`FR-NET-003`）为 **fatal 且永不重试**（11 §4）：重试等于发起新的违规请求 |

### 5.4 `FR-IPC-002` 的语义子类（`details.reason` 词汇表）

11 §3.8 只登记了"载荷校验失败"一条码，因此本文把所有**载荷语义**失败收敛到 `FR-IPC-002`，用 `details.reason` 区分（便于测试与用户文案细分）：

| `reason` | 触发 | 典型通道 |
|---|---|---|
| `not_absolute` / `dotdot_segment` / `unc_forbidden` / `symlink_forbidden` / `app_internal_path` / `outside_root` | §5.2 路径校验（`assertUserPath` / `assertContainedPath`） | 导入、`setConfig`、`fr:project:*`、`fr:agent:installSkill` |
| `not_a_regular_file` / `not_a_directory` / `nul_byte` | §5.2 | 导入、`fr:project:importFiles` |
| `relpath_invalid` / `absolute_ref_forbidden` / `backslash_forbidden` | §5.2 `assertWorkspaceRelPath`（**A5**）：工作区相对路径非法、出现绝对路径或反斜杠 | `fr:agent:send`（`attachments[].ref`）、`fr:project:listFiles`、`fr:project:importFiles` |
| `unknown_reference` | 载荷引用的 id 在主线状态中不存在：`sessionId`（阅读或 **Agent 会话**）、`tabId`、`jobId`、`requestId`、`annotationId`(hard 删除)、`projectId` | `doc:*`、`window:*`、`parser:cancel`、`translate:cancel`、`notes:delete`、`fr:agent:*`、`fr:project:*` |
| `page_out_of_range` | `page` 超出 `pageCount` | `getPageBitmap` |
| `batch_too_large` | 批字符超 `TRANSLATE_BATCH_CHARS`、`unitIds.length > 200`、`sourcePaths.length > 200`、`attachments.length > 8` | `translateUnits`、`fr:project:importFiles`、`fr:agent:send` |
| `run_in_progress` | 同一项目已有活动 run（**AG-1**：一个项目同时只有 1 个 run，同会话不得并发） | `fr:agent:send` |
| `unknown_tool` | `tool` 不在 `fr:agent:listTools` 返回的 14 个工具内（14-agent §4.1） | `fr:agent:setPermissionRule` |
| `fts_query_invalid` | FTS5 查询语法不合法 | `doc:search` |
| `empty_selection` | 既无 `collectionKeys` 也无 `itemKeys` | `zotero:importSelection` |
| `revision_conflict` | `expectRevision` 与当前不符（同码亦见 `FR-STORE-008`） | `setConfig` |

> 说明：本表是**契约层**对既有错误码取值范围的细化，不新增错误码（11 §1.2 E-5 要求码只增不改）。若后续希望为路径越界单列专用码，须走 `spec:` 变更同时修改 11 §3.8 与本节。
>
> **Agent 的 run 级失败不在此表**：它们在 `fr:agent:send` 返回之后发生，经 `fr:agent:event` 的 `kind:'error'` 回推，其 `payload.code` 取 `FR-AGT-002/004/005/006/007/008/010/011`（均已登记于 11 §3），因此**不**用 `FR-IPC-002` 表达。
>
> **边界**：涉及网络与合规的拒绝**不**用 `FR-IPC-002` —— 协议/主机/DNS/重定向类失败统一用 `FR-NET-002`（`reason=scheme_forbidden`）与 `FR-NET-003`（`reason ∈ {allowlist, denylist, user_click_unconfirmed}`，09 §2.5）。`FR-IPC-002` 只负责**载荷结构与进程内语义**。

---

## 6. 能力协商与降级

### 6.1 `fr:app:getCapabilities`

```jsonc
{ "ok": true, "data": { "parser": true, "ocr": true, "agent": true,
                        "sync": "folder", "engine": "rule", "quickMode": true } }
```

| 字段 | 类型 | 语义 | 消费方 |
|---|---|---|---|
| `parser` | `boolean` | sidecar（含 Python 运行时）可用；`false` 时解析只走 `rule` | 设置页、`fr:parser:start` 前置提示 |
| `ocr` | `boolean` | OCR 引擎与语言包可用 | 扫描件提示、`fr:parser:start` 的 `ocr` 默认值 |
| `agent` | `true` | **V1 恒 `true`**（2026-10-03 决策：V1 内置 Agent，取代 ADR-11 的「放 V2」）；`true` 时 UI **必须显示 Agent 入口**（14-agent.md）。字段仍声明为 `boolean`，`false` 保留给未来禁用场景（企业策略 / 显式关闭），届时隐藏 Agent 面板并保留 `workspace/`、`skills/`、`permissions.json` | Agent 入口的显隐 |
| `sync` | `'none'\|'webdav'\|'folder'` | 与 `app-config.schema.json` 的 `sync.provider` 取值一致；`folder` = 同步盘（ADR-09） | 同步状态条 |
| `engine` | `ParserEngine` | 当前**生效**引擎（已解析 `auto`，不含 `auto`） | 状态栏引擎徽标 |
| `quickMode` | `boolean` | **不变式**：`quickMode === (engine === 'rule')`（与 `agent` 无关，**不得**因 Agent 变化） | 快速模式横幅 |

> `agent:true` **不等于**开箱可用：未配置 LLM Provider 时会话照建但 `llmReady:false`（§4.9），UI 显示配置引导而非隐藏入口（14-agent.md §10.2）。

### 6.2 "当前为快速模式"横幅的触发

```ts
// apps/desktop/src/renderer/reader/use-quick-mode.ts
const { engine, quickMode } = useCapabilities();          // 来自 fr:app:getCapabilities
if (quickMode && engine === 'rule') render(<QuickModeBanner reason={quickReason} dismissable />);
```

- 触发条件**只有一条**：`engine === 'rule'`（`quickMode` 是其等价派生量，二者不一致即为缺陷）。`engine ∈ {docling, marker}` 时永不显示该横幅。
- 进入 `rule` 的三条路径：① 无 Python 运行时（`FR-PARSE-002`）；② sidecar 崩溃重启超 3 次进 `degraded`（04 §2.2，`FR-PARSE-001`）；③ 用户拒绝下载模型（`config.parser.consentToDownloadModels = false`，`FR-PARSE-003`）。
- 横幅**不阻塞阅读**（11 §5 D-1）；文案走 i18n `reader.banner.quickMode`，操作入口为"安装解析引擎"。
- `dismiss` 只对当次会话有效（不写盘，07 §QuickModeBanner）；引擎回到非 `rule` 后必须立即消失。

### 6.3 UI 降级矩阵（IPC 视角）

| 能力位 | 取值 | UI 行为 | 错误码 |
|---|---|---|---|
| `parser=false` | 快速模式 | 重排可用但结构精度下降；横幅常驻 | `FR-PARSE-001` `FR-PARSE-002` |
| `ocr=false` | 扫描件 | 保留原文模式；重排标注"质量可能不佳" | `FR-PARSE-006` `FR-PARSE-007` |
| `agent=true` | V1 常态 | 显示 Agent 入口与项目工作区；未配置 Provider → 会话可建（`llmReady:false`）但发送被拒并给配置引导 | `FR-AGT-001`(warn, `send` 时) `FR-AGT-012` |
| `agent=false` | 保留给未来禁用场景 | 隐藏 Agent 面板与发送入口；`workspace/`、`skills/`、`permissions.json` 保留（数据不删，仅入口隐藏） | — |
| `sync='none'` | 单机 | 隐藏同步状态；`fr:app:getConfig` 的 `sync.provider='none'` | — |
| `anchorReady=false` | 未解析 / 校验失败 | 强制 `mode='original'` 并禁用模式切换 | `FR-ANCHOR-009` `FR-LIB-005` |
| `restored.degraded=true` | 位置恢复降级 | 显示位置恢复降级横幅（**禁止静默回到文首**） | `FR-ANCHOR-011` |

---

## 7. 版本与兼容

| 规则 | 内容 |
|---|---|
| V1 | `apiVersion = 1`，写在 manifest 根与每个通道/事件的 `since` 上；`fr:app:getApiVersion` 在渲染端挂载时握手 |
| V2 | **新增通道只能追加**：新通道 `since = 当前 apiVersion`（或 `apiVersion` bump 后取新值），旧通道的 `since` 永不修改 |
| V3 | **载荷只允许非破坏性扩展**：可加可选字段、可加枚举新成员（消费方必须有 `default` 分支）、可放宽上界；**禁止**改名、删字段、收紧类型、改语义、改默认值 |
| V4 | **破坏性变更**：必须 bump `apiVersion`，并把旧通道放入 `deprecated[]`（`removedIn` 指明移除版本，至少保留 1 个 minor 周期）；渲染端以 `minSupportedApiVersion` 判断自身是否过旧（过旧 → 提示重启而非静默出错） |
| V5 | 任何通道/载荷改动**必须同步修改** `schemas/ipc-channels.json` 与本文档的通道表（README §5 第 3 条），并跑 `node specs/tools/check-specs.mjs` 与 `pnpm gen:check` |
| V6 | `pnpm gen:check` 在 `*.generated.ts` 与 schema 不一致时失败；**禁止手改生成物**（AGENTS §3） |
| V7 | 通道超时默认 30 s（`FR-IPC-003`）；单通道如需更长预算，必须在备注列显式声明，不得散落魔数 |

```ts
// 渲染端握手（apps/desktop/src/renderer/ipc/handshake.ts）
const v = await fr.app.getApiVersion();
if (v.apiVersion < RENDERER_MIN_API_VERSION) throw new AppError('FR-IPC-001', { … });
const missing = REQUIRED_CHANNELS.filter((n) => !v.channels.some((c) => c.name === n));
if (missing.length) throw new AppError('FR-IPC-001', { details: { missing: missing.join(',') } });
```

---

## 8. 测试要求

### 8.1 契约测试（每通道 ≥ 1 条，`apps/desktop/src/main/ipc/*.contract.test.ts`）

1. **happy path**：合法载荷 → `ok:true`，返回值通过 `channels[].response` 的 zod 严格校验；
2. **载荷快照**：请求/响应与 manifest 生成的 zod schema 双向一致（新增字段未入 schema 即失败）；
3. **通道存在性**：`channels[].name` 全部在 `HANDLERS` 中注册；反例（未注册通道）→ `FR-IPC-001`。

### 8.2 错误路径测试（每通道 ≥ 1 条）

| 用例 | 断言 |
|---|---|
| 缺必填字段 / 多传未知字段 | `ok:false` + `FR-IPC-002`；service 层**零调用**（mock 计数 = 0） |
| 枚举越界（如 `mode:'x'`） | `ok:false` + `FR-IPC-002` |
| 域错误（如文档不存在） | `ok:false` + 表中该通道声明的域错误码，且 `error.i18nKey`/`severity`/`retryable` 与 11 §3 一致 |
| 降级路径（如导入 > `MAX_FILE_SIZE_MB` 的 PDF、sidecar 缺失时 `fr:parser:start`） | `ok:true`，且 `warnings` 含 `FR-LIB-003`/`FR-PARSE-001`；**断言未返回 `ok:false`**（11 §5 D-2） |
| 非 `AppError` 抛出（`throw new Error()`） | 边界转换 → `FR-SYS-001`，且 `cause`/`stack` **不出现在**返回值中 |
| 超时 | 超 30 s → `FR-IPC-003`（fake timer） |

### 8.3 越权测试（必测，P0）

| # | 输入 | 断言 |
|---|---|---|
| S1 | `fr:library:import` 传 `"..\\..\\Windows\\win.ini"` | `FR-IPC-002` `reason=dotdot_segment`；**文件未被读取**（fs spy 零调用） |
| S2 | 同上传 `"C:\\Windows\\win.ini"`（绝对但非 PDF） | `FR-LIB-004`；无写入 |
| S3 | 传 `"\\\\server\\share\\a.pdf"`（UNC） | `FR-IPC-002` `reason=unc_forbidden` |
| S4 | 传指向库外的符号链接 | `FR-IPC-002` `reason=symlink_forbidden` |
| S5 | 传 `<userData>/config.json` | `FR-IPC-002` `reason=app_internal_path` |
| S6 | `fr:library:importFolder` 传 `library/<citekey>` 子目录 | 允许（读），但**不得**修改该目录；写入路径由主进程推导 |
| S7 | `fr:app:openExternal` 传 `file:///C:/Windows/win.ini` | `FR-NET-002` `reason=scheme_forbidden`；**未调用** `shell.openExternal` |
| S8 | `fr:app:openExternal` 传非白名单 https 且 `confirmedByUser:false` | `FR-NET-003`（fatal，不重试） |
| S9 | 任何通道传 `sessionId`/`tabId`/`jobId`/`requestId`/`projectId` 为伪造 ULID（含 `fr:agent:*`、`fr:project:*`） | `FR-IPC-002` `reason=unknown_reference` |
| S10 | `fr:doc:getPageBitmap` 传 `page: 99999` | `FR-IPC-002` `reason=page_out_of_range` |
| S11 | preload 桥被探测：`window.fr.invoke` / `window.fr.send` / `require` | 全部 `undefined` |
| S12 | `fr:agent:send` 的 `attachments[].ref` 传 `{"kind":"workspace","path":"C:\\Windows\\win.ini"}` | `FR-IPC-002` `reason=absolute_ref_forbidden`；**文件未被读取**（fs spy 零调用） |
| S13 | 同上传 `{"kind":"workspace","path":"../../config.json"}` 或 `{"kind":"workspace","path":"..\\..\\x.md"}` | `FR-IPC-002` `reason=dotdot_segment` / `backslash_forbidden` |
| S14 | `fr:project:listFiles` 传 `dir:"..\\.."` 或 `dir:"/etc"` | `FR-IPC-002`（`reason=dotdot_segment`/`absolute_ref_forbidden`）；且响应 `files[].path` 中**无绝对路径** |
| S15 | `fr:project:importFiles` 传 `sourcePaths:["\\\\server\\share\\a.md"]`（UNC）与指向库外的符号链接 | `FR-IPC-002` `reason=unc_forbidden` / `symlink_forbidden`；工作区**零写入** |
| S16 | `fr:agent:setPermissionRule` 传 `tool:"browse_web"`（不在 V1 的 14 个工具内） | `FR-IPC-002` `reason=unknown_tool`；`permissions.json` **未被修改** |
| S17 | `fr:agent:installSkill` 传 `sourceDir` 指向 `<userData>/config.json` 所在目录 | `FR-IPC-002` `reason=app_internal_path`；`skills/` 无写入 |
| S18 | `fr:project:exportZip` 载荷多传 `destPath`（schema 未声明） | `FR-IPC-002`（未知字段）；落盘仍只由保存对话框决定（A3） |
| S19 | 扫描 `fr:agent:*` / `fr:project:*` 的全部响应与事件载荷 | 不含绝对路径（A4）；`fr:agent:event` 只含 `argsSummary` 与 `summary`，不含完整工具参数（AG-8） |

### 8.4 事件测试

| # | 用例 | 断言 |
|---|---|---|
| E1 | `fr:parser:progress` 节流 | 1 s 内 50 次进度更新 → 渲染端收到 ≤ 10 次，且首个/末个状态不丢 |
| E2 | `seq` 单调 | 每通道从 1 递增，无重复；跳号时渲染端记 `warn: ipc.event.gap` |
| E3 | `fr:library:changed` 后可自愈 | 收到事件后 `fr:library:list` 能查到新状态（事件非真源） |
| E4 | 事件在窗口销毁后 | 不再投递，且不抛错（订阅者清理验证） |
| E5 | `fr:parser:failed` | `error.code` ∈ 11 §3 已登记码；`fallbackChain` 反映实际尝试顺序 |
| E6 | `fr:app:updateAvailable` | `mandatory:false` 时 UI 不得强制阻断使用 |
| E7 | `fr:agent:event` 跳号 | 渲染端记 `warn: ipc.event.gap`，并用 `fr:agent:getSession(afterSeq = 最后收到的会话 seq)` 补齐；补齐后消息/工具序列与 JSONL 逐行一致（AG-7 可回放） |
| E8 | `fr:agent:event` 的 `permission_required` 超时 | 120 s 无响应 → 视为 `deny`（**仅本次 run，不写盘**）；工具以 `FR-AGT-003` 回灌模型，run 不中断，UI 标注「超时视为拒绝」 |
| E9 | `fr:project:changed` 后可自愈 | 收到事件后 `fr:project:listFiles` / `fr:project:getPermissions` 能查到同一状态（事件非真源） |
| E10 | `fr:agent:event` 与 `fr:agent:getSession` 的 `seq` 一致性 | 同一会话内事件载荷的 `seq` 无重复、无空洞；外层信封 `seq` 独立单调，二者不得互相赋值（§2.3） |

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：7 条设计原则（renderer 零特权 / preload 白名单 / 禁止传 Electron 对象）、统一信封 `ApiResult<T>` 与事件信封 `{type,payload,ts,seq}`、**59 个 invoke 通道 + 6 个事件**（library 10 / doc 7 / parser 5 / notes 6 / translate 9 / fetch 4 / zotero 4 / app 11 / window 3）、7 个关键通道的完整请求响应示例、路径穿越校验伪码（`assertUserPath`/`assertContainedPath`）与 NetGuard 6 条规则、`FR-IPC-002` 语义子类词汇表、**`errors`（不可完成→`ok:false`）与 `warnings`（可完成但有降级→`ok:true`）的判据**、**与 `09-fetch-compliance.md` 对齐**（`purpose ∈ {oa-metadata,oa-fulltext,llm,asset,user-browser}`；协议/主机/DNS/重定向拒绝用 `FR-NET-002`/`FR-NET-003` 而非 `FR-IPC-002`；审计字段与 `net-audit.jsonl` 一一对应）、能力协商与快速模式横幅触发条件、版本兼容 7 条规则、契约/错误/越权/事件四类测试要求。错误码全部取自 `11-error-handling.md` §3（不新增码） |
| v1.1 | 2026-10-03 | **V1 纳入 Agent**（取代 ADR-11 的「Agent 放 V2」，权威定义见 `14-agent.md`）：新增 **15 个 invoke 通道**（`fr:agent:*` 10 个 + `fr:project:*` 5 个）与 **2 个事件**（`fr:agent:event`、`fr:project:changed`），通道总数 59 → **74**、事件 6 → **8**；`fr:app:getCapabilities.agent` 由「V1 恒 `false`」改为 **V1 恒 `true`**（`agent:true` 时 UI 显示 Agent 入口；`agent:false` 降级行改为「保留给未来禁用场景」；`quickMode === (engine === 'rule')` 不变）；§1 的 P5/P6 与 §5.2 扩展（新增 `assertWorkspaceRelPath`；`assertContainedPath` 的适用范围扩到 `fr:project:*` 与一切含路径的 Agent 载荷；绝对路径入口由 3 处 → 5 处，新增的两处必须来自系统对话框/拖放；新增硬规则 **A5**：`fr:agent:send` 的 `attachments[].ref` 只允许「文献库 `docId`」或「工作区相对路径」，**禁止绝对路径**）；§5.4 新增 `relpath_invalid`/`absolute_ref_forbidden`/`backslash_forbidden`/`run_in_progress`/`unknown_tool` 等 `FR-IPC-002` 语义子类；§3 新增 `fr:agent:*`（10）与 `fr:project:*`（5）两组通道表、事件表扩到 8 行；§4 新增 6 个关键通道完整示例（§4.8–§4.13：`send`/`start`/`getSession`/`setPermissionRule`/`importFiles`/`exportZip`）；§8 新增 S12–S19 越权用例与 E7–E10 事件用例；manifest 补 `$defs` 与两个跨文件 `$ref`（`agent-session.schema.json`/`agent-permissions.schema.json`），`apiVersion` 保持 **1**（新通道 `since = 1`）。**`errors[]` 只用 `11-error-handling.md` §3 已登记的码，不新增码**：`FR-AGT-001`（无可用 Provider，`send` 受理失败）/`FR-AGT-009`（技能非法或安装失败）/`FR-AGT-010`（会话数据损坏）/`FR-AGT-012`（项目工作区不可用）+ 跨域 `FR-STORE-001/002/012/019`；run 级失败（`FR-AGT-002/004/005/006/007/008/011`）经 `fr:agent:event` 的 `kind:'error'` 回推。**码位复用说明**：原「V2 预留」的 `FR-AGT-001/002/003` 三条语义已被 11 §3.3（v1.1）整体重写为 V1 语义（无 Provider / 模型调用失败 / 权限被拒），本文按**重写后**的语义引用，不复用旧义 |

> **跨规范一致性提示**（供实现者判断优先级）：`07-ui-spec.md` 的若干注释中出现了非规范通道写法（域名写作 `parse`/`progress`/`anchor`/`config`/`note`/`search`/`doctor`，或动作段为两段以上），`04`/`05`/`08` 亦引入了 11 §3 尚未登记的少量错误码。按 [README §2](README.md) 的优先级（`schemas/*.json` > 其余规范），**以本文件与 `schemas/ipc-channels.json` 为准**；上述差异应由后续 `spec:` 提交统一（修正文档措辞与 11 的码表），不得在实现中两套并存。
>
> **本次改动的依赖与遗留（写入范围仅本文件与 `schemas/ipc-channels.json`）**：
> 1. `11-error-handling.md` §3.3 已由并行的 `spec:` 提交把 AGT 域从「V2 预留」改为 **V1 正式域**（`FR-AGT-001..012`，`-008` 为 fatal + 永不重试的安全事件），`14-agent.md §12` 要求的 12 条码现已全部登记 —— 本文与 manifest 按该表引用，**未新增任何码**；`node specs/tools/check-specs.mjs` 的 C8 因此全绿。
> 2. `14-agent.md` 已进入 `README.md` §2 的规范索引（C10 全绿）。
> 3. **历史差异已收敛（2026-10-03 收尾）**：`08-translation.md` 要求的 `fr:translate:translateUnits` 补 `FR-TRANS-007/011/012/013/015/016/017`、`fr:translate:upsertGlossary` 补 `FR-TRANS-014`、`fr:translate:getCache` 补 `FR-TRANS-015` 已全部落地（本文表格 + manifest `errors[]` 同步）。注：`FR-TRANS-014`（术语表导入非法）语义上只属于 `upsertGlossary`，故未加入 `translateUnits`；`07-ui-spec.md` 的非规范通道写法已于同期统一。
