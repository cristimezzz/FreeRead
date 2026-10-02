# 11 · 错误处理规范（错误模型 / 错误码表 / 重试 / 降级 / 日志 / 恢复）

> 状态：**冻结**。本文件是**唯一错误码登记处**：任何 `AppError` 的 `code` 必须出现在 §3 表中，否则 `pnpm verify` 的 `fr/error-codes` 规则失败（F5、DoD 第 6 条）。
> 上游：[README §3 命名](README.md) ｜ [00-conventions §5 脱敏白名单](00-conventions.md) ｜ [03-anchor-model INV-1..10](03-anchor-model.md) ｜ [07-ui-spec 状态机与空态](07-ui-spec.md)。
> 关联：`04-parser-sidecar.md`（解析态）、`06-ipc-contract.md`（跨进程序列化）、`09-fetch-compliance.md`（NetGuard）、`05-storage.md`（doctor）。

---

## 1. 统一错误模型

### 1.1 `AppError` 定义

```ts
// packages/core/src/errors.ts
export type ErrorArea = 'LIB'|'PARSE'|'ANCHOR'|'NOTE'|'TRANS'|'FETCH'|'STORE'|'IPC'|'NET'|'UI'|'SYS'|'AGT';
/** input=用户输入/文件本身 ｜ parse=解析与锚点 ｜ storage=文件与数据库 ｜ network=网络与合规 ｜ provider=翻译 LLM
 *  ipc=进程间通信 ｜ ui=渲染交互 ｜ system=运行时环境 ｜ compliance=合规硬约束（永不重试）｜ unknown=兜底 */
export type ErrorCategory = 'input'|'parse'|'storage'|'network'|'provider'|'ipc'|'ui'|'system'|'compliance'|'unknown';
export type ErrorSeverity = 'fatal' | 'error' | 'warn';
export type ErrorCode = `FR-${ErrorArea}-${string}`;                                      // 3 位数字，见 §3
export type ErrorDetails = Readonly<Record<string, string | number | boolean | null>>;    // 必须可 JSON 序列化

export interface AppErrorOptions {
  category: ErrorCategory; severity: ErrorSeverity; retryable: boolean;
  i18nKey: string;              // 形如 `errors.FR-PARSE-001`
  details?: ErrorDetails;
  cause?: unknown;              // 仅进程内保留，跨进程前必须剥离
  message?: string;             // 面向开发者的英文描述
}

export class AppError extends Error {
  readonly code: ErrorCode; readonly category: ErrorCategory; readonly severity: ErrorSeverity;
  readonly retryable: boolean; readonly i18nKey: string;
  readonly details: ErrorDetails; readonly cause?: unknown;

  constructor(code: ErrorCode, opts: AppErrorOptions) {
    super(opts.message ?? code); this.name = 'AppError'; this.code = code; /* …Object.freeze(details)… */
  }
  /** 跨进程/落盘用：剥离 cause 与 stack，只留可序列化字段 */
  toWire(): AppErrorWire { return { code: this.code, category: this.category, severity: this.severity,
    retryable: this.retryable, i18nKey: this.i18nKey, details: { ...this.details }, message: this.message }; }
  static fromWire(w: AppErrorWire): AppError { /* 反向构造，cause 置 undefined */ }
}

export interface AppErrorWire {
  code: string; category: ErrorCategory; severity: ErrorSeverity;
  retryable: boolean; i18nKey: string;
  details: Record<string, string | number | boolean | null>; message: string;
}

/** 兜底：任何非 AppError 的 throw 在边界处必须经此转换 */
export function toAppError(e: unknown, fallback: ErrorCode = 'FR-SYS-003'): AppError;
```

### 1.2 传递规则（硬规则 E-1..E-8）

- **E-1 不得吞错**：禁止 `catch {}`（F5）；`catch (e)` 后必须 `throw toAppError(e, …)`，或**显式降级并记含错误码的 `warn`/`error` 日志**。
- **E-2 不得跨进程传原始 `Error`**：主↔渲染、sidecar↔主之间只能传 `AppErrorWire`（或 `{ ok:false, error: AppErrorWire }`）；`cause`/`stack` 只留在产生错误的进程内。
- **E-3 必须序列化**：IPC 返回值统一为 `type IpcResult<T> = { ok: true; data: T } | { ok: false; error: AppErrorWire }`，渲染侧 `unwrap()` 时重建 `AppError`。
- **E-4 边界转换点**（唯一允许调用 `toAppError` 的 5 处）：① IPC handler 最外层；② sidecar 响应解析处；③ 文件/DB 访问封装层；④ React `ErrorBoundary`；⑤ 定时任务与事件回调最外层。
- **E-5 码只增不改**：新增场景必须新增码；废弃码标 `deprecated` 并保留一年。
- **E-6 `fatal` 必须上报日志**；`fatal` 且不可重试且属 `input/parse` 类时，UI 必须提供「导出日志」。
- **E-7 语言分离**：开发者 `message` 用英文，用户文案只经 `i18nKey`（`00-conventions §1`）。
- **E-8 渲染兜底**：未捕获错误 → `FR-UI-001`（可重试 = 重新加载视图）；连续 3 次同码 → `FR-UI-002`。

---

## 2. 错误域（AREA）清单

| AREA | 职责（一句话） | AREA | 职责（一句话） |
|---|---|---|---|
| `LIB` | 文献库：导入、去重、citekey、元数据、文件缺失 | `STORE` | 存储：磁盘、权限、SQLite、索引一致性、缓存、配置 |
| `PARSE` | 解析链路：sidecar 可用性、引擎、模型、OCR、页数限制、解析确定性 | `IPC` | 进程间通信：通道未注册、载荷校验、通道超时 |
| `ANCHOR` | 锚点模型：不变量 INV-1..10 校验、patch 重放、坐标合法性 | `NET` | 网络与合规：离线、DNS/TLS、NetGuard 拦截、更新失败 |
| `NOTE` | 笔记/高亮/标注：锚点缺失、文件损坏、写入冲突 | `UI` | 渲染与交互：未捕获异常、渲染进程崩溃、字体缺失 |
| `TRANS` | 翻译：Provider 配置/鉴权/限流/超时/返回非法、术语表冲突、缓存 | `SYS` | 运行时环境：sidecar 进程崩溃、内存、Node 版本、窗口创建 |
| `FETCH` | OA 获取与元数据补全：DOI 无 OA、来源限流、引用格式非法 | `AGT` | **V1 正式域**：Agent 会话与 run、工具执行、权限判定、项目工作区、技能安装（语义真源 `14-agent.md` §12） |

---

## 3. 错误码表（117 条）

> 列含义：**级别** = `fatal`（不可继续当前操作且需用户介入）/ `error`（操作失败，可换路径）/ `warn`（降级，功能仍可用）。
> **重试** = 自动重试（`A`，参数见 §4）/ 用户确认后重试（`U`）/ 永不重试（`N`）。
> **上报** = 是否写入本地错误日志（`✔`）并是否携带堆栈（`S`）。


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-LIB-001` | PDF 文件损坏 | PDF 头/交叉引用表解析失败 | error | N | `errors.FR-LIB-001`「该文件已损坏，无法打开」 | 重新下载或更换文件 | ✔S |
| `FR-LIB-002` | PDF 已加密 | 打开时要求口令（`PasswordException`） | error | N | `errors.FR-LIB-002`「该文件受密码保护，暂不支持」 | 移除口令后重新导入 | ✔ |
| `FR-LIB-003` | 文件过大 | 字节数 > `MAX_FILE_SIZE_MB`（默认 200） | warn | N | `errors.FR-LIB-003`「文件超过 {maxSize}，导入后可能较慢」 | 继续导入 / 取消 | ✔ |
| `FR-LIB-004` | 不支持的文件格式 | 扩展名 ∉ {`.pdf`,`.epub`} 或 MIME 不符 | warn | N | `errors.FR-LIB-004`「暂不支持该格式：{ext}」 | 选择 PDF/EPUB | — |
| `FR-LIB-005` | 库内文件缺失 | `paper.pdf` 路径不存在或不可读 | error | U | `errors.FR-LIB-005`「文件已不在原路径」 | 重新定位 / 从库中移除 | ✔ |
| `FR-LIB-006` | 重复导入 | `docId`（sha256）已存在 | warn | N | `errors.FR-LIB-006`「已存在重复文档，已跳过」 | 打开已有文档 | — |
| `FR-LIB-007` | citekey 冲突 | 目标 citekey 已被**不同** `docId` 占用 | error | U | `errors.FR-LIB-007`「引用键 {citekey} 已被占用」 | 自动追加后缀 / 手动改名 | ✔ |
| `FR-LIB-008` | 元数据非法 | `meta.json` 未通过 `meta.schema.json` | warn | N | `errors.FR-LIB-008`「元数据不完整，已用文件名补全」 | 手动编辑元数据 | ✔ |
| `FR-LIB-009` | 文件正被占用 | 写入时 `EBUSY`/`EPERM`（同步盘锁定） | error | A | `errors.FR-LIB-009`「文件被其他程序占用」 | 关闭同步盘客户端后重试 | ✔ |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-PARSE-001` | sidecar 不可用 | health 探测失败或超时（`SIDECAR_HEALTH_MS`） | warn | A | `errors.FR-PARSE-001`「未检测到解析引擎，已切换快速模式」 | 安装/启动解析引擎 | ✔ |
| `FR-PARSE-002` | 无 Python 环境 | 运行时探测不到可用的 Python 3.11 | warn | N | `errors.FR-PARSE-002`「未安装 Python 运行环境，将使用内置规则排版」 | 打开诊断查看安装说明 | ✔ |
| `FR-PARSE-003` | 模型未下载 | 引擎所需权重缺失或 SHA256 校验失败 | error | U | `errors.FR-PARSE-003`「解析模型尚未下载完成」 | 下载模型（显示体积）/ 改用规则引擎 | ✔ |
| `FR-PARSE-004` | 解析任务超时 | 单批 > 120 s 无进度 | error | A | `errors.FR-PARSE-004`「解析超时，正在重试」 | 自动重试 / 切普通引擎 | ✔ |
| `FR-PARSE-005` | 解析引擎崩溃 | sidecar 进程退出码非 0 | error | A | `errors.FR-PARSE-005`「解析引擎异常退出，正在重启」 | 自动重启（限 1 次）/ 打开诊断 | ✔S |
| `FR-PARSE-006` | OCR 失败 | OCR 引擎报错或返回空 | warn | N | `errors.FR-PARSE-006`「该文件为扫描件，质量可能不佳」 | 用原文模式阅读 / 标记纠错 | ✔ |
| `FR-PARSE-007` | OCR 质量过低 | 文本覆盖率 < 60% | warn | N | `errors.FR-PARSE-007`「识别到的文字较少，重排结果可能不完整」 | 切换原文模式 | ✔ |
| `FR-PARSE-008` | 引擎不支持该文档 | 引擎显式返回 `unsupported` | error | U | `errors.FR-PARSE-008`「当前引擎无法解析该文档」 | 切换引擎（docling→marker→rule） | ✔ |
| `FR-PARSE-009` | 页数超限 | 页数 > `MAX_PAGE_COUNT`（默认 500） | warn | N | `errors.FR-PARSE-009`「文档超过 {maxPage} 页，将分批解析」 | 分批继续 / 先读原文 | ✔ |
| `FR-PARSE-010` | 解析确定性失败 | 同输入两次结果字节不一致（INV-10） | fatal | N | `errors.FR-PARSE-010`「解析结果不稳定，已阻止写入」 | 切换引擎 / 导出日志上报 | ✔S |
| `FR-PARSE-011` | 任务被取消 | 用户调用 `fr:parser:cancel` | warn | N | `errors.FR-PARSE-011`「解析已取消」 | 重新解析 | — |
| `FR-PARSE-012` | 坐标归一化失败 | 引擎返回的 bbox 无法映射为页面 pt | error | U | `errors.FR-PARSE-012`「版面坐标异常，已改用规则排版」 | 使用快速模式 / 切换引擎 | ✔S |
| `FR-PARSE-013` | sidecar 内部错误 | 未捕获异常、输出非法 JSON、输出不合 `parse-result.schema.json`、写盘失败（`ENOSPC`）、**检测到出站网络尝试**（`04` §S7） | error | A | `errors.FR-PARSE-013`「解析引擎异常，正在重试」 | 自动重试（≤1 次）/ 切换引擎 / 导出日志 | ✔S |
| `FR-PARSE-014` | sidecar 令牌/跨源拒绝 | token 缺失/错误/过期，或请求携带 `Origin` 头（`04` §S3/S4） | error | N | `errors.FR-PARSE-014`「解析引擎会话已失效」 | 由主进程重新握手（自动） | ✔ |
| `FR-PARSE-015` | 请求体过大 | `Content-Length` 或实际读取量 > `PARSE_MAX_BODY_BYTES`（32 MiB） | error | N | `errors.FR-PARSE-015`「解析请求过大」 | 分批解析 / 导出日志 | — |
| `FR-PARSE-016` | 路径越权 | `pdfPath` 不在允许根内、非常规文件、含 `..`/UNC（`04` §S6） | error | N | `errors.FR-PARSE-016`「无法访问该文件」 | 重新导入到知识库后重试 | ✔S |
| `FR-PARSE-017` | 协议错误 | 请求体不合 `parse-request.schema.json`、非法状态迁移、`Idempotency-Key` 与 `cacheKey` 不一致、`engine:"rule"` 被发往 sidecar、未知 `jobId`（`404` 同码） | error | N | `errors.FR-PARSE-017`「解析请求异常」 | 重试一次；仍失败则导出日志 | ✔S |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-ANCHOR-001` | ID 重复（INV-1） | `Block.id`/`Sentence.id` 在同一模型内重复 | fatal | N | `errors.FR-ANCHOR-001`「文档结构存在冲突，已阻止写入」 | 重新解析 / 导出日志 | ✔S |
| `FR-ANCHOR-002` | 句子行引用缺失（INV-2） | `Sentence.lines` 为空或 `LineRef.page ≠ Sentence.page` | error | N | `errors.FR-ANCHOR-002`「该句无法定位到原文位置」 | 该句降级为段落级锚点 | ✔S |
| `FR-ANCHOR-003` | 段落块引用缺失（INV-3） | `Paragraph.blockIds` 为空 | error | N | `errors.FR-ANCHOR-003`「段落结构不完整，已跳过该段」 | 跳过该段并标记纠错 | ✔ |
| `FR-ANCHOR-004` | 矩形越界（INV-4） | `Rect` 超出 `pageSize` 超过 2 pt 容差 | error | N | `errors.FR-ANCHOR-004`「版面坐标越出页面范围」 | UI 裁剪渲染 / 标记纠错 | ✔S |
| `FR-ANCHOR-005` | 行区间越界（INV-5） | `[begin, begin+len)` 超出 `lineId` 文本长度 | error | N | `errors.FR-ANCHOR-005`「行区间与实际文本长度不符」 | 截断到有效区间并记警告 | ✔S |
| `FR-ANCHOR-006` | 内容丢失（INV-6） | 非 `abandon` 块未覆盖全部文本字符 | fatal | N | `errors.FR-ANCHOR-006`「重排可能丢失内容，已阻止写入」 | 重新解析 / 切换引擎 | ✔S |
| `FR-ANCHOR-007` | 阅读顺序非单调（INV-7） | 按 `order` 遍历页号回退 | warn | N | `errors.FR-ANCHOR-007`「阅读顺序已按版面几何自动修正」 | 无需操作（已自动修正） | ✔ |
| `FR-ANCHOR-008` | 置信度越界（INV-8） | `score ∉ [0,1]` | error | N | `errors.FR-ANCHOR-008`「置信度数据异常，已按低置信处理」 | 标记为低置信并可纠错 | ✔ |
| `FR-ANCHOR-009` | Schema 校验失败（INV-9） | `blocks.json` 未通过 `doc-anchor-model.schema.json` | fatal | N | `errors.FR-ANCHOR-009`「文档结构与当前版本不兼容」 | 重新解析 / 打开诊断 | ✔S |
| `FR-ANCHOR-010` | 坐标非法 | `Rect` 含 NaN/负数/零面积 | error | N | `errors.FR-ANCHOR-010`「版面坐标无效，已忽略该区域」 | 忽略该块并标记纠错 | ✔S |
| `FR-ANCHOR-011` | 锚点无法解析 | `sentenceId`/`blockId` 在当前模型中不存在 | warn | U | `errors.FR-ANCHOR-011`「该位置已失效，已跳到相近段落」 | 重新解析 / 就近定位 | ✔ |
| `FR-ANCHOR-012` | Patch 重放失败 | `patches/*.json` 引用的 `blockId` 不存在或顺序非法 | error | U | `errors.FR-ANCHOR-012`「排版修正无法应用，已恢复原始结构」 | 删除该 patch / 重新纠错 | ✔S |
| `FR-ANCHOR-013` | 目录不可用 | `outline` 为空或标题层级全部为 0 | warn | N | `errors.FR-ANCHOR-013`「未获取到有效目录」 | 继续阅读（侧栏显示占位） | — |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-NOTE-001` | 标注文件损坏 | `annotations.jsonl` 某行 JSON 解析失败 | error | N | `errors.FR-NOTE-001`「部分笔记无法读取，已跳过损坏行」 | 打开诊断 / 导出原始文件 | ✔S |
| `FR-NOTE-002` | 锚点缺失 | 标注引用的 `sentenceId` 已不存在 | warn | U | `errors.FR-NOTE-002`「该笔记的原位置已失效」 | 就近定位 / 重新绑定 | ✔ |
| `FR-NOTE-003` | 写入冲突 | 文件 mtime/hash 与索引不一致（同步盘并发） | error | U | `errors.FR-NOTE-003`「笔记在外部被修改，请选择保留版本」 | 保留本地 / 使用磁盘版本 | ✔ |
| `FR-NOTE-004` | 译文模式不可标注 | `translationMode === 'only'` 时尝试加高亮/笔记 | warn | N | `notes.translationDisabled`「该文章无法在译文中添加高亮或笔记，请切回原文或对照模式」 | 切换到对照模式 | — |
| `FR-NOTE-005` | 删除失败 | 文件被占用或权限拒绝 | error | A | `errors.FR-NOTE-005`「删除失败，请稍后重试」 | 重试 / 打开诊断 | ✔ |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-TRANS-001` | Provider 未配置 | 无可用 Provider 或无 API Key | warn | N | `translation.providerMissing`「尚未配置翻译服务」 | 打开翻译设置 | — |
| `FR-TRANS-002` | 鉴权失败 | HTTP 401/403 或本地服务拒绝 | error | U | `errors.FR-TRANS-002`「翻译服务鉴权失败，请检查密钥」 | 打开设置更新密钥 | ✔ |
| `FR-TRANS-003` | 限流 | HTTP 429 或 `Retry-After` | warn | A | `errors.FR-TRANS-003`「翻译请求过于频繁，正在稍后重试」 | 自动退避重试 | ✔ |
| `FR-TRANS-004` | 请求超时 | 单批 > 30 s | error | A | `errors.FR-TRANS-004`「翻译超时，正在重试」 | 自动重试 / 换 Provider | ✔ |
| `FR-TRANS-005` | 连接中断 | 网络中断或进程失联 | warn | A | `errors.FR-TRANS-005`「翻译已暂停，网络恢复后继续」 | 恢复后自动继续 | ✔ |
| `FR-TRANS-006` | 返回非法 | 译文条数与请求不一致 / 空串 / 含占位符破坏 | error | A | `errors.FR-TRANS-006`「翻译结果异常，已丢弃本次结果」 | 自动重试（1 次）/ 换 Provider | ✔S |
| `FR-TRANS-007` | 术语表冲突 | 同一 `source` 映射多个不同 `target` | warn | N | `translation.glossary.conflict`「术语表存在冲突词条：{term}」 | 打开术语表修正 | ✔ |
| `FR-TRANS-008` | 文本过长 | 单段落 > 8000 字符无法分批 | warn | N | `errors.FR-TRANS-008`「该段落过长，已按句拆分翻译」 | 自动按句拆分 | — |
| `FR-TRANS-009` | 目标语言与原文相同 | 语言检测结果与 `targetLang` 一致 | warn | N | `translation.lang.sameAsSource`「检测到目标语言与原文语言相同」 | 更换目标语言 | — |
| `FR-TRANS-010` | 本地模型不可用 | Ollama 服务未启动或模型未拉取 | warn | U | `errors.FR-TRANS-010`「本地模型服务不可用」 | 启动 Ollama / 拉取模型 / 换 Provider | ✔ |
| `FR-TRANS-011` | 翻译被取消 | `AbortSignal` 触发（用户取消 / 切换文档） | warn | N | `errors.FR-TRANS-011`「翻译已取消」 | 重新发起 | — |
| `FR-TRANS-012` | 词典模式仅支持短文本 | `none` Provider 收到 `texts.length > 1` 或单条 > `TRANSLATE_DICT_MAX_CHARS` | warn | N | `errors.FR-TRANS-012`「该内容过长，无法使用离线词典」 | 选中更短文本 / 配置翻译服务 | — |
| `FR-TRANS-013` | 术语强制替换断言未过 | `08` §5.3 断言：译文仍含 `source` 且 `source !== target` | error | N | `errors.FR-TRANS-013`「术语替换校验未通过」 | 人工复核该术语（按 P0 缺陷上报） | ✔S |
| `FR-TRANS-014` | 术语表导入非法 | 缺列 / 坏 `caseSensitive` / 非 UTF-8；报文含**行号** | warn | N | `errors.FR-TRANS-014`「术语表第 {line} 行格式不正确」 | 按模板修正后重新导入 | — |
| `FR-TRANS-015` | 翻译缓存损坏 | SQLite 行不可解析 / JSONL 截断 | warn | N | `errors.FR-TRANS-015`「翻译缓存已损坏，已自动重建」 | 无需操作（已重建） | ✔ |
| `FR-TRANS-016` | 批量超限 | 单批 > `TRANSLATE_BATCH_CHARS`（编程错误，不得靠重试掩盖） | error | N | `errors.FR-TRANS-016`「翻译批次异常」 | 导出日志上报 | ✔S |
| `FR-TRANS-017` | 部分批次失败 | 某个批在重试/拆半后仍失败（其余批次照常回填） | warn | U | `errors.FR-TRANS-017`「部分段落翻译失败」 | UI 提供「重试失败段」 | ✔ |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-FETCH-001` | 无 OA 版本 | Unpaywall/OpenAlex 返回 `is_oa=false` | warn | N | `errors.FR-FETCH-001`「该文献暂无可公开获取的版本」 | 用已有 PDF 导入 / 手动打开来源页 | — |
| `FR-FETCH-002` | 来源限流 | HTTP 429 或 ToS 限制 | warn | A | `errors.FR-FETCH-002`「来源限流，正在稍后重试」 | 自动退避 | ✔ |
| `FR-FETCH-003` | DOI 非法 | DOI 正则校验失败 | warn | N | `errors.FR-FETCH-003`「DOI 格式不正确」 | 检查输入 | — |
| `FR-FETCH-004` | 元数据补全失败 | Crossref/OpenAlex 返回空或超时 | warn | A | `errors.FR-FETCH-004`「元数据补全失败，已保留原有信息」 | 手动编辑元数据 | ✔ |
| `FR-FETCH-005` | 引文格式不支持 | 导出引用时请求了未实现的 CSL 样式 | warn | N | `errors.FR-FETCH-005`「暂不支持该引文格式」 | 选择内置格式 | — |
| `FR-FETCH-006` | 下载内容非法 | `content-type` 或 `%PDF-` 魔数校验失败（`09` §6） | warn | N | `errors.FR-FETCH-006`「下载到的文件不是有效 PDF」 | 手动打开来源页 / 用已有 PDF 导入 | ✔ |
| `FR-FETCH-007` | 下载体积超限 | 单次响应超 `09` §2.3.8 上限（`ENOSPC` 归 `FR-STORE-001`） | warn | N | `errors.FR-FETCH-007`「文件超过下载体积上限」 | 手动下载后导入 | — |
| `FR-FETCH-008` | 元数据冲突待确认 | `09` §5.3 无法自动决策：保留已有值 + 标「待确认」，**不阻塞导入** | warn | N | `errors.FR-FETCH-008`「部分元数据存在冲突，请确认」 | 在详情页对比确认 | — |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-STORE-001` | 磁盘空间不足 | 可用空间 < 200 MB 或 `ENOSPC` | fatal | U | `errors.FR-STORE-001`「磁盘空间不足，无法保存」 | 清理缓存 / 更换缓存目录 | ✔ |
| `FR-STORE-002` | 权限被拒绝 | `EACCES`/`EPERM` 写入知识库目录 | fatal | U | `errors.FR-STORE-002`「没有写入权限，请检查目录权限」 | 更换库目录 / 修复权限 | ✔ |
| `FR-STORE-003` | 路径过长 | Windows `MAX_PATH` 溢出 | error | U | `errors.FR-STORE-003`「路径过长，无法写入」 | 缩短 citekey / 更换库目录 | ✔ |
| `FR-STORE-004` | SQLite 损坏 | `PRAGMA integrity_check` 非 `ok` | fatal | N | `errors.FR-STORE-004`「索引数据库已损坏，真源文件不受影响」 | 打开诊断 → 重建索引 | ✔S |
| `FR-STORE-005` | 索引不一致 | 磁盘文件与 `document` 表不一致 | warn | U | `errors.FR-STORE-005`「索引与文件不一致」 | 重建索引 | ✔ |
| `FR-STORE-006` | 迁移失败 | `schemaVersion` 迁移抛错 | fatal | N | `errors.FR-STORE-006`「数据迁移失败，已备份原文件」 | 回滚备份 / 导出日志 | ✔S |
| `FR-STORE-007` | 缓存写入失败 | 位图/译文缓存目录不可写 | warn | N | `errors.FR-STORE-007`「缓存写入失败，已跳过缓存」 | 继续（功能降级）/ 清理缓存 | ✔ |
| `FR-STORE-008` | 配置非法 | `config.json` 未通过 `app-config.schema.json` | warn | N | `errors.FR-STORE-008`「配置文件损坏，已恢复默认设置」 | 打开设置确认 | ✔ |
| `FR-STORE-012` | 文件写入失败 | 原子写协议（`05` §1.1）中 `write`/`fsync`/`rename` 失败；`ENOSPC` 归 `-001`、`EACCES` 归 `-002` | fatal | U | `errors.FR-STORE-012`「保存失败，请检查磁盘与权限」 | 清理空间 / 检查权限后重试 | ✔S |
| `FR-STORE-013` | 序列化结果不合 Schema | 内存中 `zod`/JSON Schema 校验不通过（**不落盘**） | error | N | `errors.FR-STORE-013`「数据结构异常，已阻止写入」 | 重新解析 / 导出日志 | ✔S |
| `FR-STORE-014` | citekey 非法或冲突 | 违反 `05` §3.1 规则、命中保留名、或冲突无法自动消解 | error | U | `errors.FR-STORE-014`「引用键不可用」 | 修改引用键后重试 | — |
| `FR-STORE-015` | 文件与指纹不符 | `paper.pdf` 字节 sha256 ≠ `meta.json#docId` | error | U | `errors.FR-STORE-015`「文件内容与记录不一致」 | 运行 `doctor --verify-hashes` / 重新导入 | ✔ |
| `FR-STORE-016` | 标注文件存在坏行 | `annotations.jsonl` 有不可解析行，或文件 > 64 MiB | warn | N | `errors.FR-STORE-016`「部分笔记无法读取，已跳过损坏行」 | 运行 `doctor --compact` | ✔ |
| `FR-STORE-017` | 标注锚点悬空 | 标注引用的 `sentenceId`/`blockId` 在当前模型中不存在 | warn | U | `errors.FR-STORE-017`「该笔记原位置已失效」 | 就近定位 / 重新绑定 | ✔ |
| `FR-STORE-018` | 补丁与文档不匹配 | `patches/*.json` 的 `docId`/`schemaVersion` 与当前 `blocks.json` 不符 | warn | N | `errors.FR-STORE-018`「排版修正已失效，已跳过」 | 重新纠错 / 运行 `doctor --check` | ✔ |
| `FR-STORE-019` | 导入文件超过上限 | `paper.pdf` > `MAX_PDF_BYTES`（512 MiB） | error | N | `errors.FR-STORE-019`「文件超过体积上限（{maxSize}），无法导入」 | 更换文件 / 拆分后导入 | — |
| `FR-STORE-020` | 产物文件超过上限 | `blocks.json` 等超过各自 `MAX_*_BYTES`（`05` §常量） | warn | N | `errors.FR-STORE-020`「解析产物过大，已跳过缓存」 | 继续阅读（不写缓存）/ 导出日志 | ✔ |
| `FR-STORE-021` | 数据库版本过高 | `PRAGMA user_version` > `APP_SCHEMA_VERSION`（禁止自动降级） | fatal | N | `errors.FR-STORE-021`「数据由更新版本创建，请升级 FreeRead」 | 升级应用 | ✔ |
| `FR-STORE-022` | 存在悬挂临时文件 | 原子写中断遗留的 `*.tmp`（`--check` 只报，`--clean` 才删） | warn | N | `errors.FR-STORE-022`「发现残留临时文件」 | 运行 `freeread doctor --clean` | — |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-IPC-001` | 通道未注册 | `fr:*` 不在 `ipc-channels.json` 白名单 | fatal | N | `errors.FR-IPC-001`「内部通信异常，请重启应用」 | 重启应用 / 导出日志 | ✔S |
| `FR-IPC-002` | 载荷校验失败 | zod 校验不通过 | error | N | `errors.FR-IPC-002`「内部数据校验失败」 | 重试操作 / 导出日志 | ✔S |
| `FR-IPC-003` | 通道超时 | 无响应超过 30 s | error | A | `errors.FR-IPC-003`「操作响应超时」 | 自动重试（1 次） | ✔ |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-NET-001` | 离线 | `navigator.onLine === false` 或探测失败 | warn | A | `common.state.offline`「当前处于离线状态，本地功能不受影响」 | 继续本地阅读 | — |
| `FR-NET-002` | DNS/连接失败 | `ENOTFOUND`/`ECONNREFUSED` | warn | A | `errors.FR-NET-002`「网络连接失败」 | 检查网络 / 自动重试 | ✔ |
| `FR-NET-003` | 合规拦截 | 请求域名未命中 NetGuard 白名单 | **fatal** | **N** | `errors.FR-NET-003`「该请求不在允许的来源范围内，已阻止」 | 无（合规硬约束，见 `09-fetch-compliance.md`） | ✔ |
| `FR-NET-004` | 证书/TLS 失败 | 证书校验错误 | error | N | `errors.FR-NET-004`「安全连接失败，已中止请求」 | 检查系统时间/代理 | ✔ |
| `FR-NET-005` | 更新检查失败 | 更新源不可达或返回非法 | warn | A | `errors.FR-NET-005`「检查更新失败」 | 自动重试 / 手动下载 | ✔ |
| `FR-NET-006` | SSRF / IP 字面量 / 审计不可用 | `details.reason` ∈ `ssrf_private`（DNS 解析到私网/回环/链路本地/保留地址）、`ip_literal`（`hostname` 为 IP 字面量，本地 Provider 回环例外除外）、`audit_unavailable`（审计写盘失败 → **审计不可用则不出站**） | error | N | `errors.FR-NET-006`「该请求被安全策略阻止」 | 无（例外仅限本地 Provider 回环）/ 修复磁盘后重发 | ✔S |


| 错误码 | 含义 | 触发条件 | 级别 | 重试 | 用户文案（i18n key） | 建议动作 | 上报 |
|---|---|---|---|---|---|---|---|
| `FR-UI-001` | 渲染未捕获异常 | React ErrorBoundary 捕获 | error | U | `errors.FR-UI-001`「界面出现异常，可尝试重新加载视图」 | 重新加载视图 | ✔S |
| `FR-UI-002` | 视图反复崩溃 | 同一视图 3 次同码崩溃 | fatal | N | `errors.FR-UI-002`「该视图持续异常，已回到文献库」 | 导出日志并上报 | ✔S |
| `FR-UI-003` | 渲染进程崩溃 | 进程 `render-process-gone` | fatal | U | `errors.FR-UI-003`「界面进程异常退出，正在恢复阅读位置」 | 自动重开并恢复位置（§7.1） | ✔S |
| `FR-UI-004` | 字体加载失败 | 内置字体文件缺失 | warn | N | `errors.FR-UI-004`「字体加载失败，已使用系统字体」 | 继续（视觉降级） | ✔ |
| `FR-SYS-001` | 未预期异常兜底 | 穷尽分支 `never` 命中或未知异常 | fatal | N | `common.error.unknown`「出现未知错误，已记录日志」 | 导出日志 | ✔S |
| `FR-SYS-002` | 内存不足 | 堆使用超 `MEMORY_PEAK_MB`（1200 MB） | fatal | U | `errors.FR-SYS-002`「内存不足，建议关闭其他文档」 | 关闭文档 / 清理缓存 | ✔ |
| `FR-SYS-003` | 主进程异常 | 主进程未捕获异常 | fatal | N | `errors.FR-SYS-003`「应用发生异常，即将重启」 | 重启并做完整性检查（§7.2） | ✔S |
| `FR-SYS-004` | Node/Electron 版本不满足 | 运行时版本低于最低要求 | fatal | N | `errors.FR-SYS-004`「运行环境版本过低」 | 查看最低版本要求 | ✔ |
| `FR-AGT-001` | 未配置可用 LLM Provider | `fr:agent:send` 时无可用 Provider（`ollama` 未启动且未配置 `openai-compatible` Key），或全部候选 `health().ok === false`（`14-agent.md` §10.2） | warn | N | `errors.FR-AGT-001`「尚未配置可用模型，Agent 无法作答」 | 打开模型设置（本地 Ollama 或自备 Key） | — |
| `FR-AGT-002` | 模型调用失败/超时 | `LlmProvider.chat` 抛错（网络中断、401/403、429、5xx），或流式响应在 `RUN_TIMEOUT_MS`（600 s）内无任何 chunk | error | A | `errors.FR-AGT-002`「模型调用失败，正在重试」 | 自动重试（≤ 1 次）→ 仍失败则结束 run 并保留已产出内容；可换模型/Provider | ✔ |
| `FR-AGT-003` | 工具权限被拒（`deny`） | 权限规则为 `deny`：用户显式「拒绝」、`ask` 超时 120 s 兜底（仅本次 run）、或 `permissions.json` 已持久化 `deny`；**AG-9 终态，同项目不再询问** | warn | N | `errors.FR-AGT-003`「该操作未获授权，已跳过」 | 在权限面板改为「允许一次」或「总是允许」 | ✔ |
| `FR-AGT-004` | 工具参数非法 | 模型给出的工具参数未通过该工具 `inputSchema`（zod 严格对象）校验，或 `argsJson` 解析失败（ReAct-文本模式解析失败重试 1 次后，`14-agent.md` §10.1） | error | N | `errors.FR-AGT-004`「工具参数不合法，已请模型重新生成」 | 无（重试由 Agent 自身在处理模型轮次时进行）；连续失败建议更换模型 | ✔ |
| `FR-AGT-005` | 工具执行失败 | 工具 `execute()` 抛错或返回 `ok:false`（非权限、非参数）：文件/SQLite IO 失败、`TOOL_TIMEOUT_MS`（30 s）超时、Pyodide 崩溃或超时、产物写入失败 | error | U | `errors.FR-AGT-005`「工具执行失败：{tool}」 | 重试该工具 / 改用其他工具 / 打开诊断 | ✔ |
| `FR-AGT-006` | 达到步数或工具调用上限 | `steps > MAX_STEPS`（24）或单 run 工具调用数 > `MAX_TOOL_CALLS`（40）；终止并**保留已产出内容**（AG-6） | warn | N | `errors.FR-AGT-006`「本次步骤已达上限，已给出阶段性结论」 | 继续追问可继续（在已产出内容上接着做） | ✔ |
| `FR-AGT-007` | run 被取消 | 用户点「停止」/ `fr:agent:cancel`，或切换项目、删除会话；`AbortSignal` 透传到 Provider 与正在执行的工具 | warn | N | `errors.FR-AGT-007`「已停止本次回答」 | 保留已有产出；可直接继续追问 | — |
| `FR-AGT-008` | 沙箱越界 | 文件类工具入参经 `realpath` + 包含性校验失败（`..`、符号链接逃逸、UNC、NUL 字节、工作区外绝对路径），或工具尝试绕过 `NetGuard` 出网（AG-3/AG-5；`14-agent.md` §4.2） | **fatal** | **N** | `errors.FR-AGT-008`「检测到越权访问，已阻止并记录」 | 无（安全事件）；导出日志上报 | ✔S |
| `FR-AGT-009` | 技能非法或安装失败 | `SKILL.md` 缺失或 front-matter 不合规（`name` 不匹配 `^[a-z0-9][a-z0-9-]{1,39}$`、`description` > 200 字符、`license` 不在允许清单）、路径穿越、文件数 > 200 或总体积 > 20 MiB（`14-agent.md` §9） | error | N | `errors.FR-AGT-009`「技能包不合法，未安装」 | 修正 `SKILL.md` 后重新安装 / 更换来源目录 | ✔ |
| `FR-AGT-010` | 会话数据损坏 | `sessions/<sessionId>.jsonl` 存在不可解析行，或事件行未通过 `agent-session.schema.json`（未知 `type`、`seq` 非单调、多余字段；AG-7） | error | U | `errors.FR-AGT-010`「会话记录损坏，已跳过坏行」 | 导出会话备份后删除该会话并新建 | ✔S |
| `FR-AGT-011` | 上下文超预算且无法压缩 | 压缩（裁项目元信息 → 旧工具结果转 `summary` → 对话 rollup）后仍 > `TOKEN_BUDGET`（120_000）；终止并保留已产出内容（AG-6） | warn | N | `errors.FR-AGT-011`「对话上下文已满，请开启新会话」 | 开启新会话 / 缩小检索范围 | ✔ |
| `FR-AGT-012` | 项目工作区不可用 | `projects/<projectId>/` 被移动或删除、无读写权限（`ENOENT`/`EACCES`/`EPERM`）、或所在磁盘不可写 | error | U | `errors.FR-AGT-012`「项目目录不可用」 | 更换目录 / 重新创建项目 | ✔ |

> **INV 覆盖自检**：INV-1→`FR-ANCHOR-001`；INV-2→`-002`；INV-3→`-003`；INV-4→`-004`；INV-5→`-005`；INV-6→`-006`；INV-7→`-007`；INV-8→`-008`；INV-9→`-009`；INV-10→`FR-PARSE-010`。**10/10 已映射。**

---

## 4. 重试策略

```ts
// packages/core/src/retry.ts
export interface RetryPolicy { maxAttempts: number; baseMs: number; factor: number; jitterRatio: number; capMs: number; retryOn: (e: AppError) => boolean }
export const DEFAULT_RETRY: RetryPolicy = {
  maxAttempts: 3, baseMs: 500, factor: 2, jitterRatio: 0.2, capMs: 8000,
  retryOn: (e) => e.retryable && e.severity !== 'fatal',
};
// 第 n 次重试延迟 = min(capMs, baseMs * factor^(n-1)) * (1 + rand(-jitterRatio, +jitterRatio))
// n=1 → 500ms(±20%)；n=2 → 1000ms(±20%)；maxAttempts 含首次尝试（即最多 2 次重试）
```

| 类别 | 策略 | 代表错误码 |
|---|---|---|
| **自动重试**（指数退避，最多 3 次尝试） | 瞬时故障：网络抖动、限流、超时、文件占用、引擎崩溃（限 1 次重启） | `FR-NET-002`、`FR-TRANS-003/004/005/006`、`FR-FETCH-002`、`FR-STORE-007`、`FR-IPC-003`、`FR-LIB-009`、`FR-PARSE-001/004`、`FR-AGT-002`（模型调用，≤ 1 次） |
| **用户确认后重试**（不自动） | 需改变外部条件或存在数据风险 | `FR-LIB-005/007`、`FR-PARSE-003/008/012`、`FR-STORE-001/002/005`、`FR-NOTE-003`、`FR-ANCHOR-011/012`、`FR-TRANS-002/010`、`FR-NET-005`、`FR-AGT-005/010/012` |
| **永不重试** | ① 合规拦截（`FR-NET-003`，每次重试都是新的违规请求）；② 结构/确定性失败（`FR-ANCHOR-001/006/009`、`FR-PARSE-010`）；③ 输入本身不合法（`FR-LIB-001/002/004`、`FR-FETCH-003/005`、`FR-SYS-004`）；④ 用户主动取消（`FR-PARSE-011`、`FR-NOTE-004`、`FR-TRANS-009`）；⑤ **Agent 终态与安全**：权限 `deny` 终态（`FR-AGT-003`，AG-9 明确"不得再询问"，重试等于绕过用户决定）、沙箱越界（`FR-AGT-008`，安全事件，重试即又一次越权尝试）、run 取消（`FR-AGT-007`）、参数非法（`FR-AGT-004`，重试由 Agent 在下一轮模型交互中自行处理，不由重试层发起）、未配置 Provider（`FR-AGT-001`）、步数上限（`FR-AGT-006`）、上下文超预算（`FR-AGT-011`） | 同左 |

补充规则：**T-1** 重试必须透传同一 `clientEventId`（`02-domain-model` 的幂等键），避免重复写文件；**T-2** 重试期间 UI 必须可见（面板/`StatusBar` 显示「正在重试 n/3」），不得静默循环；**T-3** `fatal` 禁止自动重试（`retryOn` 已强制）；**T-4** 同一错误码 60 s 内重试超 6 次 → 熔断并转为用户确认（记 `warn: error.circuitOpen`）。

---

## 5. 降级矩阵（能力 × 失败 → 行为）

| 能力 | 失败 | 降级行为 | 用户可见 | 错误码 |
|---|---|---|---|---|
| 版面解析（sidecar） | 不可用 / 无 Python | 使用 `rule` 引擎（XY-Cut + 行聚类）；顶部 `QuickModeBanner`；`score` 由启发式给出（0.5/0.65） | 快速模式横幅 + 「安装解析引擎」 | `FR-PARSE-001/002` |
| 版面解析（docling） | 崩溃 / 超时 | 自动重启 1 次 → 失败则整篇降级到 `rule`，**不混用引擎** | 横幅提示已降级 | `FR-PARSE-004/005` |
| OCR | 失败 / 质量过低 | 保留原文模式；重排视图标注「扫描件质量可能不佳」；允许人工纠错 | `reader.banner.ocrQuality` | `FR-PARSE-006/007` |
| 锚点（单句级） | `LineRef` 缺失 / 越界 | **降级为段落级锚点**（`paragraphId`），高亮落在整段矩形；笔记仍可保存 | 该句高亮呈整段样式 + 提示 | `FR-ANCHOR-002/005/011` |
| 重排渲染 | 块结构校验失败 | 该文档仅提供原文模式；`/reader` 强制 `mode='original'` 并禁用切换按钮 | 提示「该文档结构与当前版本不兼容」 | `FR-ANCHOR-006/009` |
| 翻译 Provider | 未配置 / 鉴权失败 | 显示原文；面板提示；提供内置词典划词翻译 | `translation.providerMissing` | `FR-TRANS-001/002` |
| 翻译 Provider | 限流 / 超时 | 退避重试 3 次；仍失败则暂停任务，保留已译段落（**不丢弃**） | 面板「继续」按钮 | `FR-TRANS-003/004/005` |
| 翻译 Provider | 返回非法 | 丢弃本次结果并重试 1 次；再失败则标记该段失败，其余继续 | `translation.paragraphFailed` | `FR-TRANS-006` |
| OA 获取 | 无 OA / 限流 | 保留本地已有 PDF；提供「用已有文件导入」；**绝不回退到任何绕过渠道** | `errors.FR-FETCH-001` | `FR-FETCH-001/002` |
| 网络（全局） | 离线 | 阅读/笔记/纠错/缓存译文全部可用；翻译仅用缓存；获取与更新入口禁用 | `common.state.offline` | `FR-NET-001` |
| SQLite 索引 | 损坏 / 不一致 | **真源（磁盘文件）仍可读**：降级为直接扫描知识库目录构建内存索引，并提示重建 | 库顶部警告条 + 「重建索引」 | `FR-STORE-004/005` |
| 缓存目录 / 配置 | 不可写 / 非法 | 跳过缓存（位图按需重生成、译文每次重取）；配置加载默认值并备份 `config.json.bak` | 状态栏与设置页提示 | `FR-STORE-007/008` |
| 更新 | 失败 | 静默重试 3 次后停止，不打断使用 | 设置页显示「检查更新失败」 | `FR-NET-005` |
| 渲染进程 | 崩溃 | 重开窗口并恢复到上次 `sentenceId`（§7.1） | 提示「正在恢复阅读位置」 | `FR-UI-003` |
| Agent（V1） | 权限被拒（`ask` → 用户「拒绝」） | 该次工具调用不执行并记审计（`permission` 事件）；run 继续，模型改走其他路径或结束；**不影响阅读等其余功能** | 权限面板提示「已拒绝」 | `FR-AGT-003` |
| Agent（V1） | 权限规则 `deny`（终态，AG-9） | 工具**直接失败且不再询问**（不弹窗、不写盘变更），模型只能换工具或结束 | 权限面板显示「已拒绝（永久）」+ 可改回 | `FR-AGT-003` |
| Agent（V1） | 模型不支持工具调用（`supportsTools === false`） | 进入 **ReAct-文本模式**：提示词要求模型输出严格 JSON `{"tool":…,"args":{…}}`，由主进程解析；解析失败重试 1 次后以 `FR-AGT-004` 结束 | 会话开始横幅「当前模型不支持原生工具调用，可靠性下降」 | `FR-AGT-004` |
| Agent（V1） | `run_python` 不可用（Pyodide 加载失败） | **仅禁用该工具**（`fr:agent:listTools` 标为不可用），其余 13 个工具照常工作；模型收到不可用原因后可换路径 | 该工具卡片置灰 + 提示「沙箱不可用」 | `FR-AGT-005` |

**降级总原则（D-1..D-3）**：① **阅读永不被降级阻断**（P1）；② 降级必须**可见**（横幅/状态栏/面板文案），禁止静默改变行为；③ 降级不得改变已落盘数据的语义（只影响本次会话的渲染与调度）。

---

## 6. 日志与脱敏

### 6.1 字段规范（`00-conventions §5`）

```ts
logger.error('parse.failed', {          // 事件名 domain.action（小写点分），字段 snake_case，时间 UTC 毫秒整数
  code: 'FR-PARSE-005', area: 'PARSE', severity: 'error', category: 'parse',   // 四项必填
  doc_id: 'a3f…', citekey: 'smith2020attention', engine: 'docling', page: 12,  // doc_id 存在则必填
  retryable: true, attempt: 2, i18n_key: 'errors.FR-PARSE-005', elapsed_ms: 4120,
  stack_hash: 'sha256:9f2c…',           // 堆栈只记 hash（前 16 位），不记全文
  details: { exit_code: 1 },            // 只允许可 JSON 序列化的标量
});
```

日志文件 `%APPDATA%/FreeRead/logs/app-YYYY-MM-DD.log`，保留 7 天，**默认不上传**；`fatal`/`error` 必记，`warn` 记降级与重试，`debug` 默认关闭。

### 6.2 脱敏（导出前**强制**执行）

**禁止写入日志的字段**（白名单制，违反即 CI 失败）：`api_key`、`token`、`authorization`、`password`、`cookie`、`set-cookie`、任何已配置密钥的值、文件绝对路径中的用户名段、笔记全文、译文全文（只记 `length` 与 `sha256` 前 16 位）。

导出流程（`fr:app:exportLogs`）：① 主进程读取 `logs/*.log`（最多 7 天）；② `Redactor.apply(text)` 依次执行五步——(a) 按字段名删除整行/整键（`api_key|token|authorization|password|cookie`），(b) 密钥正则 `/(sk-[A-Za-z0-9]{16,}|gh[pous]_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})/g` → `[REDACTED_SECRET]`，(c) 路径脱敏 `C:\Users\<name>\`→`%USERPROFILE%\`、`/home/<name>/`→`~/`、`/Users/<name>/`→`~/`，(d) 邮箱脱敏 `/([\w.+-]+)@([\w-]+\.[\w.-]+)/` → `$1***@$2`（保留域名以便诊断来源方联系问题），(e) 长文本字段替换为 `{len, sha256_16}`；③ 打包 zip（`logs/` + `doctor-report.json` + `app-version.json`）；④ 系统保存对话框由用户自选位置，导出内容不得出现任何密钥明文；⑤ 记 `info: { event: 'logs.exported', files: n, bytes: m }`（不记内容）。

**Redactor 单测（必须）**：输入含 `sk-…` 与 `C:\Users\alice\…` 的样本，断言输出中不出现原字符串；断言 `notes.md` 全文不出现在导出包内。

---

## 7. 崩溃与恢复

### 7.1 渲染进程崩溃（`FR-UI-003`）

```
render-process-gone
  → 主进程读取最近一次 fr:progress:save 的记录（doc_id, sentence_id, mode, updated_at）
  → 重开 BrowserWindow（同一 citekey）→ 渲染侧 ReaderView 以 initialSentenceId 进入：
       · 命中 sentenceId   → 滚动到该句并聚焦（记 info: 'reader.position.restored'）
       · 未命中（模型变了）→ 用同页首个 sentenceId，显示 reader.banner.positionRestoredDegraded
       · 无记录            → 落到第 1 页并记 warn: 'reader.position.missing'
  → 位置写入节流 ≤ 1 s，三处触发（滚动停止 500ms / visibilitychange / beforeunload）
```

**硬要求**：位置恢复是 P0 门禁（`03-anchor-model` 的锚点一致性是其前提）；恢复失败必须**可见**（横幅），禁止静默回到文首（对齐调研报告 §7.5「每次打开回到文章开头」抱怨）。

### 7.2 主进程异常退出（`FR-SYS-003`）

下次启动的**启动自检序列**（≤ 2 s，不阻塞首屏；结果写入 `/doctor`）：

| 步骤 | 检查 | 失败处理 |
|---|---|---|| 1 | `PRAGMA integrity_check`（`index.sqlite`） | 失败 → `FR-STORE-004` → 损坏库改名 `index.sqlite.corrupt-<ts>`、新建空库、`/doctor` 提示「重建索引」（真源文件不丢） |
| 2 | `document` 表行数 vs `library/*/meta.json` 数量 | 不一致 → `FR-STORE-005` → `/library` 顶部警告条 + 一键重建 |
| 3 | `blocks.json` 的 `schemaVersion` 与当前一致 | 不一致 → 触发迁移；迁移失败 → `FR-STORE-006`，保留备份并禁用该文档重排模式 |
| 4 | sidecar 健康（`SIDECAR_HEALTH_MS=1500`） | 失败 → `FR-PARSE-001` 快速模式横幅（不阻断） |
| 5 | 缓存目录可写 + 用量 | 不可写 → `FR-STORE-007`；超限 → 按 LRU 清理至 `CACHE_MAX_MB`（500 MB）以内 |

**崩溃循环保护**：同一版本连续崩溃 ≥ 3 次 → 启动进入**安全模式**（禁用 sidecar、禁用翻译自动调度、禁用 GPU 加速），显示「以安全模式启动」横幅 + 「导出日志」。

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：`AppError` 模型与传递规则 E-1..E-8、12 个错误域、**80 条错误码**（含 INV-1..10 全量映射）、重试策略（base 500ms / factor 2 / maxAttempts 3 / jitter 20%）、降级矩阵、日志脱敏与导出流程、渲染/主进程崩溃恢复与安全模式 |
| v1.1 | 2026-10-03 | **AGT 域由「V2 预留」转为 V1 正式域**（Agent 会话、工具执行、权限、工作区、技能；语义真源 `14-agent.md` §12）：① `FR-AGT-001..012` **共 12 条重写**（原 `-001/002/003` 三条「V2 预留」含义全部替换，码位复用为 V1 语义；`-004..012` 为新增，其中 `-008` 为 **fatal + 永不重试 + `✔S`** 的安全事件）；② §4 重试策略补 `FR-AGT-002` 自动重试（≤ 1 次），并在「永不重试」新增第 ⑤ 类「Agent 终态与安全」（含 `FR-AGT-003` 权限 `deny` 终态、`FR-AGT-008` 沙箱越界）；③ §5 降级矩阵「Agent（V2）」行改为「Agent（V1）」，并新增权限 `deny` 终态、模型不支持工具调用 → ReAct-文本模式、`run_python` 不可用（仅禁用该工具）三行；④ §3 表头计数按实际行数校正为 **117 条** |