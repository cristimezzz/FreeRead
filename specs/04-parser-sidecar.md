# 04 · 解析 Sidecar 协议与引擎适配

> 状态：**冻结**。本文件定义主进程与 `services/parser`（Python sidecar）之间的全部通信契约、任务生命周期、引擎适配与降级规则。
> 上游依据：`plan/FreeRead-技术方案与里程碑.md` ADR-04（sidecar）、§3.1（架构）、§5（M2）、§6（测试）；优先级见 `README.md` §2。
> 本文件**不重新定义** `DocAnchorModel`、`Block`、`Sentence`、`LineRef`、INV-1..10、算法 A1/A2 与质量指标：一律引用 `03-anchor-model.md`。

---

## 1. 目的与边界

sidecar 是**唯一**的版面解析执行体：输入 PDF 路径 + 解析选项，输出符合 `schemas/doc-anchor-model.schema.json` 的 `DocAnchorModel`（知识库中的 `blocks.json`，见 `03` §6.7）。

| # | 硬边界（违反 = P0 缺陷，PR 拒绝） | 机检方式 |
|---|---|---|
| B1 | **只产出 `DocAnchorModel`**；绝不产出 HTML / Markdown 成品 / 任何渲染结果 | 响应体必须通过 `parse-result.schema.json` 校验；`services/parser/**` grep 禁止 `html`/`to_html`/`render_html`（`export_to_html` 等调用在适配层剥离，§5.3） |
| B2 | **绝不访问互联网**：不发起任何出站连接；模型与语言包由主进程经 NetGuard 下载（§7.2） | `services/parser/tests/test_offline.py` patch `socket.connect`，任何出站即失败（§8 S7） |
| B3 | 只监听 `127.0.0.1`，端口由 OS 动态分配（`--port 0`） | 启动断言 + T-P11 |
| B4 | 不写知识库目录；只写 `%APPDATA%/FreeRead/cache/parser/` 与日志目录 | T-P12（只读挂载知识库） |
| B5 | 不读 `config.json`、不读 Keychain、不读环境变量中的凭据 | 代码审查 + grep 门禁 |
| B6 | **不做**句子切分（A2）、块-行关联（A1）、`order` 指派、`Block.id` 生成 | 这些是主进程 `packages/core` 的职责（`03` §6.3–6.5）；sidecar 只输出 `RawBlock`（§5.2） |

> **为何 A1/A2 不在 sidecar**：`LineRef.lineId` 来自 PDF.js `getTextContent()`（`03` §6.1），而 PDF.js 在 Electron 主进程侧。sidecar 自行切分会与 PDF.js 的行划分不一致，直接破坏 INV-2/INV-5。故 sidecar 产物是"带 pt 坐标与类型的版面块"，`DocAnchorModel` 由主进程锚点构建器合成。

---

## 2. 进程与生命周期

### 2.1 启动与握手

```bash
python -m freeread_parser --port 0 --token <32-byte-hex> \
  --cache-dir "%APPDATA%/FreeRead/cache/parser" --log-dir "%APPDATA%/FreeRead/logs" \
  --library-root "%USERPROFILE%/FreeRead/library" --max-concurrency 1 [--offline]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--port` | 是 | 固定 `0`：由 OS 分配空闲端口（§8 S2） |
| `--token` | 是 | 每会话随机 token（hex 64 字符）；启动后**必须**从 `sys.argv` 移除，避免被任务管理器读出 |
| `--cache-dir` / `--log-dir` | 是 | 模型与中间产物根（§7.1）/ 日志目录（§2.3） |
| `--library-root` | 是 | 允许解析的文件白名单根（§8 S6） |
| `--max-concurrency` | 否 | 并发解析上限，默认 `1`（§4.2） |
| `--offline` | 否 | 强制离线：任何需要下载的动作立即返回 `FR-PARSE-003` |

绑定端口成功后，sidecar 在 stdout 输出**恰好一行** JSON 并 `flush`，此后 stdout 只允许 NDJSON 日志（§2.3）：
`{"freeread_parser":1,"port":54123,"pid":24188,"version":"0.1.0","token_fingerprint":"sha256:ab12…"}`
主进程：① 读首行，超时 `SIDECAR_HANDSHAKE_MS = 2000`；② 失败/缺 `port`/进程提前退出 → 记 `parse.sidecar.handshake_failed` 并按 §2.2 重启；③ `GET /v1/health` 必须 `ok:true` 且 `version` 与握手一致。

### 2.2 生命周期、健康检查、重启

| 状态 | 进入条件 | 主进程动作 |
|---|---|---|
| `starting` | `spawn()` 已调用 | 等握手；超时 → kill + 退避重启 |
| `ready` | 握手成功且 health `ok:true` | 接受 `POST /v1/parse` |
| `busy` | 存在 `running` 任务 | health 仍 `ok:true`（含 `queueDepth`） |
| `degraded` | 无任何可用引擎 | health `ok:false`，主进程切 `rule`（§5.6） |
| `recycling` | 空闲超时或内存超限 | 停发新任务，回收后回 `starting` |
| `stopped` | 优雅关闭完成 | 清空队列，保留已完成批次 |

- 健康检查：`ready` 态每 5 s 一次 `GET /v1/health`（`SIDECAR_HEALTH_INTERVAL_MS = 5000`）；单次超时即判无响应（`SIDECAR_HEALTH_MS = 1500`，**已冻结**于 `00-conventions.md` §9 `BUDGETS`）；**连续 3 次失败 → 重启**。
- 空闲回收：无 `queued`/`running` 任务且空闲超 `SIDECAR_IDLE_TTL_MS = 300000`（5 min）→ 优雅停止，下次解析再启动。
- 优雅关闭：先取消在跑任务 → 等 `SIDECAR_SHUTDOWN_MS = 3000` → `terminate()` → 再等 3 s → `kill()`。
- 崩溃重启：指数退避 `500 ms → 1 s → 2 s`（报 `FR-PARSE-005`），**最多 3 次**（`SIDECAR_RESTART_MAX = 3`）；超限进 `degraded`，UI 常驻"快速模式"横幅（i18n `errors.FR-PARSE-001`），后续解析全部走 `rule`；连续 `ready` 存活 ≥ 60 s（`SIDECAR_BACKOFF_RESET_MS = 60000`）后退避计数归零。
- 崩溃时的任务：**不自动重放**；由 `ParserClient` 按 `cacheKey` 决定是否重新提交（§4.4–4.5），并把错误经 `fr:parser:progress`（`state='failed'` + `error`）下发（该事件的载荷类型由 `06-ipc-contract.md` 定义）。

> 本节与 §10.4 新增的常量必须加入 `packages/core/src/budgets.ts` 的 `BUDGETS` 并在 `10-testing.md` 登记指标卡（`00-conventions.md` §9 强制）。

### 2.3 stdout / stderr / 日志

| 流 | 约定 |
|---|---|
| stdout | 首行握手 JSON（§2.1）；此后**仅** NDJSON：`{"ts":<UTC ms>,"level":"info","event":"parse.started","doc_id":"…","job_id":"…","fields":{…}}`。禁止 tqdm/进度条等非 JSON 内容（引擎 stdout 必须在适配层重定向到 stderr） |
| stderr | 未捕获异常堆栈与第三方库原始日志；主进程加 `[parser]` 前缀转发到主日志（`debug` 级） |
| 日志文件 | `%APPDATA%/FreeRead/logs/parser-YYYY-MM-DD.log`，按天轮转、保留 7 天、默认不上传（同 `00-conventions.md` §5） |
| 脱敏 | **禁止**记录 `token`、`authorization`、绝对路径中的用户名段、PDF 全文或块文本（只记 `len` 与 `sha256` 前 8 位） |

---

## 3. HTTP API 契约

公共约定：基址 `http://127.0.0.1:<port>/v1`；响应 `Content-Type: application/json; charset=utf-8`；除 `GET /v1/health` 外**必须**带 `Authorization: Bearer <token>`（恒定时间比较）；请求体上限 `PARSE_MAX_BODY_BYTES = 33554432`（32 MiB），超限 `413` + `FR-PARSE-015`；请求体先经 `schemas/parse-request.schema.json` 校验再进业务逻辑，错误体见 §9.1。

### 3.1 `GET /v1/health`（无需 token）

- `200`：`{"ok":true,"version":"0.1.0","pid":24188,"uptimeMs":120345,"engines":[{"name":"docling","available":true,"version":"2.5.1","reason":null},…],"ocrLanguages":["en","zh"],"queueDepth":0,"running":0,"modelsReady":true}`
- `503`：`ok:false` + `FR-PARSE-005`/`006`，`engines[].reason` 说明原因。
- 语义：进程存活即必须响应；`engines` 必须列出全部 4 个名字，`rule` 的 `available` 恒为 `true`（它由主进程实现，sidecar 仅登记）。
- **与 IPC 契约的关系**：主进程把本响应**归一化**为 `ipc-channels.json` 的 `ParserHealthResponse`（`{ok,state,engines[],version,pythonVersion,pid,port,latencyMs}`，`additionalProperties:false`）——其中 `engines` 是**名字数组**，因此本响应的 `engines[].name` 必须恰好取自 `ParserEngine` 枚举 `{docling,marker,grobid,rule}`（四个引擎各占一个槽位），序号与 `state` 由主进程依 §2.2 的状态机填入。

### 3.2 `POST /v1/parse`

| 项 | 内容 |
|---|---|
| 请求体 | `schemas/parse-request.schema.json`：`{docId,pdfPath,citekey?,options{engine,ocr,langs[],maxPages?,force?},cacheKey}` |
| 请求头 | `Idempotency-Key: <cacheKey>`（可选，与体内 `cacheKey` 不一致 → `400` + `FR-PARSE-017`） |
| `202` | `{"jobId":"job_01J…","state":"queued","progress":0,"engine":"docling","cacheKey":"…","createdAt":1759449600000,"reused":false}` |
| `200` | 同上但 `reused:true`：`cacheKey` 命中缓存或在跑任务（§4.5），返回既有 `jobId` |
| 错误 | `400` `FR-PARSE-017`；`401` `FR-PARSE-014`；`403` `FR-PARSE-016`；`409` `FR-PARSE-011`；`410` `FR-LIB-005`；`413` `FR-PARSE-009`/`FR-LIB-003`；`415` `FR-LIB-004`；`422` `FR-LIB-002`/`FR-PARSE-008`；`424` `FR-PARSE-002/003`；`500` `FR-PARSE-005/006/013`；`503` `FR-PARSE-001`；`504` `FR-PARSE-004` |
| 语义 | 立即返回，不等解析完成；进度由 §3.3 轮询 |

### 3.3 `GET /v1/jobs/{jobId}`

- 查询参数：`wait=<0..30000>`（长轮询，任务仍在 `queued`/`running` 时挂起至状态变化或超时）；`include=result`（可选）。
- `200`：`schemas/parse-result.schema.json`：`{jobId,state,progress,engine,cacheKey,createdAt,stage?,fallbackChain?,reused?,error?,result?}`。
- `404`：`FR-PARSE-012`（未知或已过期 `jobId`）。
- 语义：`result` 仅在 `state=done` 时必填、其余状态禁止出现；`error` 仅在 `failed` 时出现；终态在内存保留 ≥ 10 min（`JOB_RETENTION_MS = 600000`）供重复查询。

### 3.4 `POST /v1/jobs/{jobId}/cancel`

- 请求体 `{}`；`202`：`{"jobId":"job_…","state":"canceled","canceledAt":1759449600000}`；`404` `FR-PARSE-012`；`409` `FR-PARSE-014`（任务已 `done`；对 `failed`/`canceled` 幂等返回 `202`）。
- **协作式取消**：引擎在每页/每批（≤ 50 页）边界检查取消标志；取消后必须清理临时文件并**不写入** `blocks.json`。

### 3.5 `GET /v1/engines`

- `200`：`{"engines":[{"name":"docling","kind":"model","version":"2.5.1","license":"MIT","available":true,"models":[{"id":"layout-heron","sizeBytes":172000000,"sha256":"…","present":true}],"rawLabels":["title","section_header",…]},{"name":"marker",…},{"name":"grobid",…},{"name":"rule","kind":"builtin","version":"1.0.0","license":"AGPL-3.0",…}],"ocr":[{"name":"paddleocr","license":"Apache-2.0","langs":["en","zh"]},{"name":"tesseract","license":"Apache-2.0","langs":["en","zh"]}]}`
- 语义：主进程启动后调用一次，用于"设置 → 解析引擎"页、校验 `options.engine` 可用性、生成 `THIRD_PARTY_NOTICES` 的模型条目（`plan` §6.3）。`license` 必须是 SPDX 标识符且不在 License Gate 黑名单（`GPL-2.0-only`/SSPL/BUSL/Elastic/专有/CC-BY-NC）。
- **字段映射（→ IPC `fr:parser:listEngines` 的 `ParserListEnginesResponse.engines[]`）**：`name → id`、`models[].sizeBytes` 之和 → `modelSizeBytes`、`present:false` 或任一模型缺失 → `requiresDownload:true` 与 `available:false`、`kind`+`rawLabels` → `capabilities`（`docling/marker → ["layout","ocr"]`、`grobid → ["metadata","references"]`、`rule → ["layout"]`）、`version`/`license` 原样透传。

---

## 4. 任务模型

### 4.1 `ParseJob` 状态机

`queued → running → done`；`queued → canceled`（提交后立即取消，不进入解析）；`running → canceled`（协作式取消）；`running → failed`（回退链耗尽 / 超时 / 输出非法）。

| 迁移 | 触发 | 附加动作 |
|---|---|---|
| `queued → running` | worker 空出且并发未满 | 写 `parse.started`；创建 `cache/parser/<cacheKey>/tmp/` |
| `running → done` | 全部批次完成且通过 §5.2 契约校验 | 原子落盘（先写 `.tmp` 再 `os.replace`） |
| `running → failed` | 回退链耗尽 / 超时 / 输出非法 | 写 `parse.failed`；保留 `tmp/` 供诊断（≤ 24 h） |
| `queued\|running → canceled` | `POST …/cancel` | 删除 `tmp/`，`error` 留空 |
| 终态 | `done`/`failed`/`canceled` | 不可再迁移；非法迁移 → `FR-PARSE-017` + 日志 `parse.state.invalid`（禁止静默忽略） |

### 4.2 并发与队列

| 项 | 默认 | 上限 | 说明 |
|---|---|---|---|
| 并发解析任务 | `1` | `4`（`--max-concurrency`） | 模型推理内存敏感，默认串行；>1 时每任务独立引擎实例（必须线程安全） |
| 队列长度 | `32` | `32` | 超出 → `503` + `FR-PARSE-005`（`details.reason='queue_full'`） |
| 队列调度 | FIFO | — | 同一 `docId` 只允许 1 个非终态任务；重复提交返回既有 `jobId` + `reused:true` |
| 单任务超时 | `PARSE_JOB_TIMEOUT_MS = 900000` | — | 超时 → `FR-PARSE-004`；建议按页数缩放：`max(120000, pages × 6000)`；单批 > 120 s 无进度亦判超时（与 `11-error-handling.md` §3.2 一致） |

### 4.3 进度上报粒度

每完成 **1 页**（`totalPages ≤ 50`）或每 **1 批 50 页**（`totalPages > 50`）更新一次：`progress = min(1, completedPages / totalPages)`，保留 3 位小数，`PARSE_BATCH_PAGES = 50`（与 `03` §9"极端页数分页解析"一致）。主进程必须以 IPC 事件 `fr:parser:progress` 转发给 renderer，载荷为 `ipc-channels.json` 的 `ParseProgressEvent`：`{jobId,docId,engine,state,progress,stage,pagesDone,pagesTotal,etaMs?,error?}`（`additionalProperties:false`，节流 ≥ 100 ms，状态跃迁必发）。**stage 映射**（`07-ui-spec.md` 只消费这里的取值）：

| sidecar 内部阶段 | `ParseProgressEvent.stage` |
|---|---|
| 等待/解析入队 | `queued` |
| 文本层/版面预处理 | `extracting_text` |
| 版面块识别（docling/marker） | `layout` |
| `ocr=true` 且 OCR 通道启用 | `ocr` |
| 参考文献与元数据（grobid/正则） | `postprocess` |
| 合批落盘 `blocks.json` | `writing` |
| 终态 | `done` |

`docId`/`state`/`engine` 必须与 `/v1/jobs/{jobId}` 的响应一致；`error` 字段仅在失败时非空，且 `code` 为 §9.2 的规范错误码。

**IPC 选项映射**：`fr:parser:start` 的 `ocr: boolean` 映射到请求体 `options.ocr`：`true → 'auto'`、`false → 'never'`（不做"强制全部页 OCR"的默认行为）；`always` 仅供设置页的显式选项使用。

### 4.4 断点续传

中间产物目录（**可删、可重建**，不计入知识库真源）：

```
%APPDATA%/FreeRead/cache/parser/<cacheKey>/
├─ job.json                # {"jobId","docId","engine","engineVersion","batchPages":50,"totalPages":N,"createdAt"}
├─ blocks.batch-001.json   # 第 1 批（页 1..50）的 RawBlock[]，原子写；批号 3 位补零
├─ blocks.json             # 全部批次合并的最终 RawBlock[]
└─ tmp/                    # 引擎工作目录（转换后 PDF、页位图）；取消/失败时清理
```

1. 批次文件存在且 `job.json` 的 `docId`+`engine`+`engineVersion`+`batchPages` 完全一致 → **跳过该批**直接复用；
2. 恢复条件：`cacheKey` 相同且 `options.force=false`；`force=true` 必须先清空该目录再全量重跑；
3. **与 `05-storage.md` 的关系**：`blocks.json` 的最终归属地仍是 `library/<citekey>/blocks.json`（真源）——sidecar 只写缓存目录，主进程在 `done` 后执行"校验 → 原子写入知识库 → 更新 SQLite 索引"；
4. 缓存总量受 `BUDGETS.CACHE_MAX_MB`（500 MB）约束，LRU 清理顺序：`tmp/` > 最早的 `blocks.batch-*.json` > 最旧的整个 `cacheKey` 目录。

### 4.5 幂等性

| 场景 | 行为 |
|---|---|
| 同 `cacheKey` 且缓存 `blocks.json` 存在 | 新建 job 但立即 `done`，`reused:true`，**不重复推理** |
| 同 `cacheKey` 且存在非终态任务 | 返回既有 `jobId`（`202`，`reused:true`），不新建任务 |
| 同 `cacheKey` 且上次 `failed` | 允许新建（`reused:false`），并在 `details.previousError` 回带上次错误码 |
| 不同 `cacheKey` | 独立任务，互不影响 |
| `cacheKey` 计算 | 由**主进程**按 `03` §8 计算：`sha256(docId + engine.name + engine.version + schemaVersion + PARSER_RULES_REVISION)`；sidecar 只校验 `^[0-9a-f]{64}$`，不自行计算 |

---

## 5. 引擎适配层

### 5.1 统一坐标规范

`03` §3 是唯一坐标真源：**PDF pt、原点页面左上角、y 轴向下、视觉方向（已按 `/Rotate` 归一化）、3 位小数、序列化去尾零**。适配层必须实现以下流水线，并由 T-P3 覆盖：

```
raw(x0,y0,x1,y1, pageW, pageH, rotate, space)
 1. space=normalized(0..1) → 乘 pageW/pageH                        # marker 的归一化输出
 2. space=pdf_native        → 若 y 向上则 y' = pageH − y            # 底左 → 顶左
 3. rotate 归一化：旋到视觉方向（rotate ∈ {0,90,180,270}，逆时针；旋转后交换 w/h）
 4. 统一为顶左原点：(x,y) = (min(x0,x1), min(y0,y1)), (w,h) = (|x1−x0|, |y1−y0|)
 5. 裁剪到 [0,pageW]×[0,pageH]（|溢出| ≤ 2 pt 合法，见 INV-4；超出则裁剪并记 warn parse.bbox.clipped）
 6. round(x,3)：丢弃 −0.0，去尾零
```

| 引擎 | 原生坐标 | 需要的换算 |
|---|---|---|
| `docling` | `BoundingBox` = PDF pt、**底左原点**、`coord_origin=BOTTOMLEFT`（部分版本 `TOPLEFT`，以 `bbox.coord_origin` 为准） | 步骤 2 + 3 + 5 + 6 |
| `marker` | `PolygonBox`（4 点多边形）；`page.get_bbox()` 为 0..1 归一化或 PDF pt（取决于 `pdftext` 版本） | 步骤 1 + 多边形取包围盒（与点序无关）+ 2 + 3 + 5 + 6 |
| `grobid` | TEI `<coords>` = `page,x,y,w,h`（PDF pt，**顶左**，1-based 页） | 1-based → `page`、5、6；**无坐标时按 §5.6 用纯文本模式** |
| OCR（PaddleOCR/Tesseract） | 行框 4 点（像素，页位图坐标，dpi 由渲染决定） | `pt = px × 72 / dpi`，再 2 + 3 + 5 + 6 |

### 5.2 `RawBlock`（sidecar → 主进程的中间契约）

```jsonc
{"page":3, "rect":{"x":72.1,"y":301.4,"w":210.3,"h":11.8},  // pt、顶左、3 位小数
 "type":"text",              // 已映射到 03 的 BlockType（§5.4）
 "rawLabel":"section_header",// 引擎原始标签，仅用于诊断与日志
 "score":0.9, "orderHint":12,// orderHint 可 null；主进程按 03 §6.4 校验或覆盖
 "text":"…",                 // NFC 规范化；无文本层时来自 OCR
 "source":"native"}          // "native" | "ocr"
```

`id`/`order`/`lines`/`Sentence`/`Paragraph` 一律由主进程按 `03` 补齐；sidecar **不得**生成。

### 5.3 引擎清单与使用场景

| 引擎 | 定位 | 用途 | 许可 | 备注 |
|---|---|---|---|---|
| `docling` | ✅ 默认 | 数字版 PDF 的完整语义版面 | MIT | 必须剥离 `export_to_html/markdown` 路径（B1）；只取 `DoclingDocument` 的 `texts/tables/pictures` 与 `prov` 坐标 |
| `marker` | 兜底 | 表格/公式密集文档；docling 失败时接管 | Apache-2.0（权重须 Apache/兼容；**禁止** CC-BY-NC 权重） | 允许 `--force_ocr`，但仅在 §6.1 触发条件下 |
| `grobid` | 辅助 | **仅**元数据（题名/作者/摘要）与参考文献，不产出正文块 | Apache-2.0 | 独立 HTTP 服务或本地 jar；V1 允许缺席（`available:false` 不算错误） |
| `rule` | 降级 | 无 sidecar / 启动失败时的纯 JS 降级（文本行聚类 + XY-Cut） | AGPL-3.0（主仓） | **由主进程实现，不在 sidecar 内**；`GET /v1/engines` 仅登记，`POST /v1/parse` 收到 `engine:"rule"` 必须 `400` + `FR-PARSE-017` |

### 5.4 `BlockType` 映射表（覆盖全部 14 个取值）

原则：**未识别标签一律 `text`**；类型置信不足时优先 `text`（可纠错）而非 `abandon`（会丢内容，INV-6）。

| 目标 `BlockType` | docling（`DocLayNet`/`DocItemLabel`） | marker（`LayoutLabel`/`BlockTypes`） | grobid（TEI 路径） | 备注 |
|---|---|---|---|---|
| `title` | `title`、`document_title`（第 1 页且字号全文最大） | `Title`；`SectionHeader` 且 `page=1` 且为全文首块 | `//titleStmt/title` | 与 `heading` 判别：`level=-1` 归 `title`（`03` §6.6） |
| `author` | `author`、`creator`（元数据区） | `Text`/`SectionHeader` 位于题名块下方 ≤ 60 pt 且含 `,`/`and`/上标数字骨架 | `//sourceDesc//author` | 无引擎标签时由元数据推断 |
| `abstract` | `abstract`；`section_header` 文本等于 `Abstract`/`摘要` 的段 | `SectionHeader` 匹配 `^(Abstract|摘要)\b` 之后的同区文本 | `//abstract` | 中文期刊取 `摘要` |
| `heading` | `section_header`、`heading` | `SectionHeader` | `/body/div/head` | `level` 由编号模式推定（`03` §6.6） |
| `text` | `text`、`paragraph`、`list_item`、`body`；`caption`（无匹配图/表时）；**其余全部未识别标签** | `Text`、`ListItem`；`Footnote` 落在页脚区时改判 `abandon` | `/body/div/p` | 兜底类型 |
| `figure` | `picture`、`figure`、`chart`、`image` | `Picture`、`Figure` | —（不产出） | 需与 `figure_caption` 同页配对（`03` §6.6） |
| `figure_caption` | `caption` 且与 `picture` 垂直距离 ≤ 24 pt | `Caption` 且与 `Picture` 相邻 | `//figure/figDesc` | 图注在图上/下方均可 |
| `table` | `table` | `Table` | `//table` | 表格只给纯文本，**禁止 HTML** |
| `table_caption` | `caption` 且与 `table` 垂直距离 ≤ 24 pt | `Caption` 且与 `Table` 相邻 | `//table/head` | — |
| `formula` | `formula`（行间） | `Equation`、`Formula` | `//formula[@type='display']` | 整块 1 个 `Sentence`（`03` A2 步骤 1）；`text` 存 LaTeX 原文 |
| `inline_formula` | `formula` 且宽 < 行高 × 3 且与正文行同基线 | `Equation` 落在 `Text` 行内 | `//formula[@type='inline']` | 主进程按 `03` §9 挖空并写 `\u0000fml:{blockId}\u0000` |
| `reference` | `reference`、`bibliography`、`citation`（参考文献区） | `Reference`、`Bibliography` | `/text/back//listBibl/biblStruct` | `doi` 由主进程正则提取 |
| `aside` | `aside`、`footnote`（非页脚区）、`funding` | `Footnote`、`Aside` | `//note[@place='margin']` | 页边注、基金信息 |
| `abandon` | `page_header`、`page_footer`、`page_number`、`watermark`、`copyright`、`running_title` | `PageHeader`、`PageFooter` | — | **仅 `abandon` 允许在重排视图不显示**（`03` §5）；判别 = 位于页面上/下 8% 边缘带或文本匹配页码/页眉模式 |

映射函数必须是**纯函数 + 全表覆盖**，单测对 14 个取值各断言 ≥ 1 条原始标签（T-P4）。

### 5.5 `score` 赋值规则

严格遵循 `03` §6.2"模型输出 `0.9` / 启发式兜底 `0.5`"，细化如下（**禁止**任何平滑、加权、取引擎分类概率等"更聪明"的算法——会破坏跨引擎可比性与黄金集门禁）：

| 来源 | `score` | 说明 |
|---|---|---|
| 模型分类输出（docling/marker） | `0.9` | 统一值，保证 INV-10 确定性；不用引擎浮点概率（跨版本不稳定） |
| 启发式判定（标题/图注/表注/参考文献区/`abandon` 边缘带） | `0.5` | 与"模型输出"可区分 |
| OCR 通道产出的块 | `0.5` | 文本非原生文本层 |
| `grobid` 元数据块 | `0.9` | 属模型输出 |
| 兜底 `text` 块（未识别标签） | `0.5` | 保证 `score < BUDGETS.LOW_CONFIDENCE_THRESHOLD (0.60)` → UI 可纠错（INV-8） |
| `rule` 引擎（主进程实现） | `0.5`；聚类边界清晰 `0.65` | 由 `03` §9 规定，此处仅复述 |

### 5.6 失败回退链

`docling → marker → rule`（`rule` 由主进程实现）；`grobid` 永不作为正文主引擎，其失败只降级元数据与参考文献。

| 约束 | 规定 |
|---|---|
| 何时降级 | 引擎不可用（缺模型/缺依赖/服务未起，记 `warn parse.engine.unavailable`）或执行失败（异常/超时/输出非法）→ 降级下一跳 |
| 不混用 | 同一文档只用一个正文引擎（`03` §6.2），docling 与 marker 结果**不得拼接** |
| 降级留痕 | 每次降级写 `parse.engine.fallback` 日志，并在响应 `fallbackChain` 回带（如 `["docling","marker"]`） |
| 引擎身份 | `DocAnchorModel.engine` 必须是**最终实际使用**的引擎及其版本 |
| 尝试上限 | 每个引擎最多 1 次（不重试同引擎）；总尝试 ≤ 3 |
| 不可降级错误 | `FR-PARSE-001/002/003`（文件本身不可读）**不降级**，直接失败 |
| 用户指定引擎 | 请求 `engine:"marker"` 时回退链为 `marker → rule`（尊重用户选择，不得偷偷改用 docling） |
| 全部失败 | `state=failed`，`error.code` 为原始错误码，无法判定时用 `FR-PARSE-005` |

---

## 6. OCR 通道

### 6.1 触发条件

| 条件 | 判定 |
|---|---|
| 页级触发 | 该页文本层非空白字符数 **< 20**（`03` §9），或文本行 < 2 且存在覆盖页面积 ≥ 60% 的图像 XObject |
| 文档级触发 | `scanPages / totalPages ≥ 0.6`，或 `scanPages ≥ 3` 且前 5 页中 ≥ 2 页为扫描页 → **整篇**走 OCR（避免频繁切换流水线） |
| 显式 | `options.ocr='always'` → 全部页 OCR；`'never'` → 禁用（扫描页无文本块，记 `parse.ocr.skipped`） |
| 默认 | `options.ocr='auto'`，不满足上述条件则不 OCR |

### 6.2 引擎选择与语言包

| 优先级 | 引擎 | 许可 | 选择条件 |
|---|---|---|---|
| 1 | **PaddleOCR** | Apache-2.0 | 默认（中文/混排效果更好，`plan` ADR-06） |
| 2 | **Tesseract** | Apache-2.0 | PaddleOCR 不可用（依赖/模型缺失、初始化失败）或用户显式配置 |
| — | 两者皆不可用 | — | `state=failed`，`FR-PARSE-006`，`retryable=true`（`11-error-handling.md` §3.2）；主进程可改用 `rule` + 原始位图阅读 |

| 项 | 规定 |
|---|---|
| 语言映射 | 请求 `options.langs` → PaddleOCR：`en→en`、`zh→ch`、`ja→japan`、`ko→korean`；Tesseract：`eng`/`chi_sim`/`jpn`/`kor` |
| 下载执行者 | **主进程**经 NetGuard 白名单域名下载（`plan` §4.4）；sidecar **绝不下载**（B2），只消费 `--cache-dir` 中已存在的文件 |
| 校验 | 下载后必须比对 `services/parser/models.lock.json`：`{"id":"paddleocr-ch","file":"ch_PP-OCRv4_det_infer.tar","sizeBytes":…,"sha256":"…","license":"Apache-2.0","source":"…"}`；**校验失败必须删除且不得使用**（`FR-PARSE-003`，`retryable=true`） |
| 离线 | 模型缺失且离线 → `FR-PARSE-003`（`retryable=false`），UI 提供"切换到快速模式（rule）"入口 |
| 缓存目录 | `%APPDATA%/FreeRead/cache/models/ocr/<engine>/<lang>/`（§7.1） |

### 6.3 OCR 行框 → `LineRef` 合成（确定性）

```
对每一页 P：
  nativeLines = PDF.js 在该页产出的行数（可为 0）
  OCR 行框按 (y 中心升序, x 升序) 稳定排序；竖排按 (x 降序, y 升序)（03 §9）
  第 i 个行框（0-based）→ lineId = nativeLines + i          # 每页独立，从 0 递增
  text = 行框内识别文本，去首尾空白，Unicode NFC
  rect = 行框 4 点包围盒 → pt（§5.1 步骤 1/2/5/6）
```

- 字符区间 `begin/len` 由主进程在 A1/A2 中填充，sidecar 不产出 `LineRef`；
- 同一 `y` 带被误合并的行，须按"横向间隙 > 2 × 中位字宽"切成两行；
- 行级置信度 < `BUDGETS.LOW_CONFIDENCE_THRESHOLD` 的行，其所属块 `score = 0.5`，并计入 `parse.ocr.lowconf`；
- 引擎线程数固定为 1，禁止多线程乱序写入与时间戳参与结果（INV-10）。

### 6.4 质量标记与上限

- 质量标记：全文 OCR → `meta.quality='ocr'`；原生页与 OCR 页混合 → `'mixed'`；全部原生 → `'native'`（`meta` 为 `doc-anchor-model.schema.json` 的可选字段，见 `03` §9）。
- 页数上限 `OCR_MAX_PAGE = 320`：`totalPages > 320` 时**只 OCR 前 320 页**，其余页记 `warn parse.ocr.page_limit`，**不得**因此判任务失败；`options.maxPages` 只能收紧、不能放大该上限。
- 超时：单页预算 `OCR_PAGE_TIMEOUT_MS = 20000`；超时页跳过并记 `parse.ocr.timeout`；连续 5 页超时 → 判定 OCR 通道不可用 → `FR-PARSE-006`。
- 质量过低：OCR 文本覆盖率 < 60% 时**任务仍为 `done`**，只回带 `FR-PARSE-007`（`warn`，见 `11-error-handling.md` §3.2）与 `details.coverage`，由 UI 提示"扫描件质量可能不佳"。

---

## 7. 模型与依赖管理

### 7.1 目录布局

```
%APPDATA%/FreeRead/                      # macOS: ~/Library/Application Support/FreeRead
├─ cache/
│  ├─ parser/<cacheKey>/                 # §4.4 中间产物
│  ├─ models/{layout/<engine>/<modelId>/, ocr/<engine>/<lang>/, grobid/}
│  └─ pages/                             # 页位图（见 05-storage.md）
└─ logs/parser-YYYY-MM-DD.log
```

### 7.2 首次下载交互（由主进程实现，sidecar 只报缺失）

1. `GET /v1/engines` 发现 `present:false` → 弹确认框（i18n `settings.parser.modelDownload.confirm`），列出模型 id、体积、许可、来源域名；
2. 用户确认 → 经 NetGuard 下载，UI 显示进度（复用 `fr:parser:progress` 与 `stage='postprocess'` 的节流规则，`details` 带模型 id 与已下载字节）与"取消"按钮；取消 = `AbortController.abort()` + 删除半成品；
3. 完成 → SHA256 校验 → 更新 `models.lock.json` 的 `present` → 重新调用 `GET /v1/engines`；
4. 用户拒绝 → 本次及后续解析走 `rule`，UI 常驻"快速模式"横幅（文案键 `errors.FR-PARSE-001`，见 `11-error-handling.md` §3.2），设置页保留"再次下载"入口。

### 7.3 离线场景

| 场景 | 行为 |
|---|---|
| 模型就绪 + 断网 | 完全正常（sidecar 无出站需求，B2） |
| 模型缺失 + 断网 | 不做任何下载尝试，直接 `FR-PARSE-003`（`retryable=false`）并建议快速模式 |
| GROBID 缺失 | **不算错误**：`references` 为空数组 + `warn parse.grobid.missing`（`03` §6.6 允许正则兜底切分） |
| 用户勾选"离线模式" | 主进程以 `--offline` 启动，任何需要下载的动作立即 `FR-PARSE-003` |

### 7.4 体积预算

| 产物 | 预算 | 说明 |
|---|---|---|
| 安装包内 sidecar 运行时（Python + 依赖 + 代码） | **150–300 MB** | 不含模型权重（`plan` ADR-01/§12.2） |
| docling 版面模型（按需） | ≤ 250 MB | 首次启用重排时下载 |
| marker 模型（按需） | ≤ 400 MB | 仅选择 marker 时下载 |
| PaddleOCR（检测+识别+方向分类，单语言） | ≤ 120 MB | 中文优先 |
| Tesseract 语言包 | ≤ 25 MB / 语言 | 兜底 |
| GROBID（可选） | ≤ 350 MB（含 JVM 依赖） | 默认不下载 |

`pnpm size` 与 `services/parser/scripts/check_licenses.py` 必须在 CI 校验上述上限，超标即失败（`plan` §6.3）。

---

## 8. 安全

| # | 要求 | 实现与验证 |
|---|---|---|
| S1 | 仅监听 `127.0.0.1` | `HTTPServer(("127.0.0.1", port))`；禁止 `0.0.0.0`/`::`；T-P11 断言 `getsockname()[0] == "127.0.0.1"` |
| S2 | 随机端口 | `--port 0`，端口只经 stdout 握手暴露；**禁止端口缓存/复用**。与 `01-architecture.md` §3 启动时序的差异说明：该处"读取上次端口缓存"改为"若上一会话进程仍存活则直接 `GET /v1/health`（端口取自本会话内存记录），否则跳过探测、在首次解析时 `spawn` 新进程并握手取端口"——`COLD_START_MS = 2500` 的预算不受影响，因为**任何启动路径都不同步等待 sidecar**（`01-architecture.md` §3） |
| S3 | 每会话随机 token | 主进程 `crypto.randomBytes(32)`；`Authorization: Bearer <token>`；`hmac.compare_digest` 恒定时间比较；失败 → `401` + `FR-PARSE-014`；`SIGTERM` 后失效 |
| S4 | 拒绝跨源 | 请求带 `Origin` 头（浏览器上下文）→ 直接 `403` + `FR-PARSE-014`（防 DNS rebinding / 本地网页探测） |
| S5 | 请求体上限 | 读前检查 `Content-Length`，流式读取时再次累计校验；超限 → `413` + `FR-PARSE-015` |
| S6 | 路径穿越防护 | `pdfPath` 必须同时满足：① `resolve()` 后位于 `--library-root` 或用户显式授权的 `--extra-allowed-root` 之内；② 后缀 `.pdf`（大小写不敏感）；③ 是常规文件（非指向外部的符号链接）；④ `realpath` 后仍满足 ①。任一不满足 → `403` + `FR-PARSE-016`。禁止接受 `..`、UNC 路径、`file://` URL |
| S7 | 禁止任何出站网络 | CI 在解析全程 patch `socket.connect`/`create_connection`/`urllib`，任何调用即失败；运行时若检测到出站尝试 → 记 `parse.network.blocked` 并以 `FR-PARSE-013` 终止任务 |
| S8 | 最小权限 | 不以管理员/root 运行；工作目录设为 `cache/parser/<cacheKey>/tmp`；除 `--cache-dir`/`--log-dir`/`--library-root` 外不读用户主目录 |
| S9 | 不落敏感内容 | `tmp/` 转换产物随任务结束删除；`blocks.batch-*.json` 只含结构数据，不含译文与笔记 |

---

## 9. 错误码

### 9.1 错误响应体

```jsonc
{"code":"FR-PARSE-003",                                    // 规范错误码，见 §9.2
 "message":"model docling-layout-heron missing: sha256 mismatch",  // 英文，面向开发者，≤ 300 字符
 "retryable":true,
 "details":{"modelId":"layout-heron","expected":"ab12…","actual":"cd34…","fallbackChain":["docling"]}}
```

**编码规则（强制）**：§9.2 的「规范错误码」是**权威**，`docId`/`jobId` 由 URL 与请求体携带，不重复放入响应体。`message` **禁止**直接展示给用户；UI 必须用 `code` 查 `11-error-handling.md` §3.2 的 `errors.FR-<AREA>-NNN` 映射取文案（`00-conventions.md` §1、F6）。sidecar 返回的 `code` 必须**原样**透传给渲染进程的 `ErrorObject.code`，禁止包装成新码。

### 9.2 错误码表

**来源规则**：HTTP 传输层无法表达"文件损坏 / 加密 / 格式不支持 / 文件过大"这类**库级**语义，故 sidecar 对这些情况直接返回 `11-error-handling.md` 的**跨区规范码**（`FR-LIB-002/003/004/005`），不再自造 `FR-PARSE` 码；`FR-PARSE-001..012` 的含义**完全沿用**该表，禁止改义；只有既有码无法覆盖的协议层错误才新增 `FR-PARSE-013..017`（须补登记进 `11-error-handling.md` §3.2）。

| 规范错误码 | HTTP | 含义 | 触发条件 | 可重试 | 用户文案（i18n key） |
|---|---|---|---|---|---|
| `FR-PARSE-001` | `503` | sidecar 不可用 | 进程未启动/启动失败/health 探测失败；`POST /v1/parse` 无可用引擎且无回退，或队列已满（`details.reason='queue_full'`） | 是（退避重启，§2.2） | `errors.FR-PARSE-001` |
| `FR-PARSE-002` | `424` | 无 Python 环境 | 运行时探测不到可用的 Python 3.11（sidecar 自身不可达，由主进程判定） | 否 | `errors.FR-PARSE-002` |
| `FR-PARSE-003` | `424` | 模型未下载 | 引擎权重/语言包缺失或 SHA256 校验失败（`details.modelId`） | 是（用户确认后下载，§7.2） | `errors.FR-PARSE-003` |
| `FR-PARSE-004` | `504` | 解析任务超时 | 单批 > 120 s 无进度，或整任务超 `PARSE_JOB_TIMEOUT_MS`（`details.batch`、`details.pagesDone`） | 是（自动重试/降级引擎） | `errors.FR-PARSE-004` |
| `FR-PARSE-005` | `500` | 解析引擎崩溃 | 引擎子进程/服务退出码非 0，或连续异常（`details.exitCode`） | 是（自动重启限 1 次，§2.2） | `errors.FR-PARSE-005` |
| `FR-PARSE-006` | `500` | OCR 失败 | OCR 引擎报错/返回空、初始化失败、连续 5 页超时（§6.4） | 是（回退 Tesseract，T-F8） | `errors.FR-PARSE-006` |
| `FR-PARSE-007` | `200`+`meta` | OCR 质量过低 | OCR 文本覆盖率 < 60%（**非错误**：任务照常 `done`，仅置 `meta.quality='ocr'` 并回带 `details.coverage`） | 否 | `errors.FR-PARSE-007` |
| `FR-PARSE-008` | `422` | 引擎不支持该文档 | 引擎显式返回 `unsupported`（如纯图片 PDF 交给 grobid、加密流交给 marker） | 否（切换引擎 → 回退链） | `errors.FR-PARSE-008` |
| `FR-PARSE-009` | `413` | 页数超限 | `pageCount > MAX_PAGE_COUNT`（默认 500）；sidecar 仅在 `options.maxPages` 被显式给出且更小时据此拒绝 | 否（**分批解析**：主进程按 50 页/批续跑，§4.4） | `errors.FR-PARSE-009` |
| `FR-PARSE-010` | `500` | 解析确定性失败 | 同输入两次结果字节不一致（INV-10），或批次文件校验不一致 | 否（阻止写入，切换引擎） | `errors.FR-PARSE-010` |
| `FR-PARSE-011` | `409` | 任务被取消 | 用户调用 `fr:parser:cancel`；`GET /v1/jobs/{jobId}` 返回 `state='canceled'` + 该码 | 否 | `errors.FR-PARSE-011` |
| `FR-PARSE-012` | `500` | 坐标归一化失败 | 引擎 bbox 无法映射为页面 pt（NaN/非法旋转/缺 `pageSize`）；**单块失败不中断**，该块标 `score=0.5` 并累计 `details.blockCount` | 否（改用规则排版） | `errors.FR-PARSE-012` |
| `FR-PARSE-013` | `500` | sidecar 内部错误 | 未捕获异常、输出非法 JSON、输出不合 `parse-result.schema.json`、写盘失败（ENOSPC）、检测到出站网络尝试（S7） | 是（最多 1 次） | `errors.FR-PARSE-013`（**待登记**） |
| `FR-PARSE-014` | `401`（跨源 `403`） | 不是本会话 | token 缺失/错误/过期，或请求带 `Origin` 头（S3/S4） | 否（由主进程重新握手） | `errors.FR-PARSE-014`（**待登记**） |
| `FR-PARSE-015` | `413` | 请求体过大 | `Content-Length` 或实际读取量 > `PARSE_MAX_BODY_BYTES`（32 MiB）（S5） | 否 | `errors.FR-PARSE-015`（**待登记**） |
| `FR-PARSE-016` | `403` | 路径越权 | `pdfPath` 不在允许根内、非常规文件、含 `..`/UNC（S6） | 否 | `errors.FR-PARSE-016`（**待登记**） |
| `FR-PARSE-017` | `400` | 协议错误 | 请求体不合 `parse-request.schema.json`、非法状态迁移、`Idempotency-Key` 与 `cacheKey` 不一致、`engine:"rule"` 被发往 sidecar、未知 `jobId`（`404` 亦用此码） | 否 | `errors.FR-PARSE-017`（**待登记**） |
| `FR-LIB-002` | `422` | PDF 已加密 | 存在 `/Encrypt` 且空密码打不开 | 否（移除口令后重新导入） | `errors.FR-LIB-002` |
| `FR-LIB-003` | `413` | 文件过大 | 文件字节数 > `MAX_FILE_SIZE_MB`（默认 200）；sidecar 在 open 前用 `stat` 判定 | 否 | `errors.FR-LIB-003` |
| `FR-LIB-004` | `415` | 不支持的文件格式 | magic bytes ≠ `%PDF-` 或后缀非 `.pdf` | 否 | `errors.FR-LIB-004` |
| `FR-LIB-005` | `410` | 库内文件缺失 | `pdfPath` 不存在或不可读（含被同步盘移走） | 用户重新定位后重试 | `errors.FR-LIB-005` |

**边界**：`FR-ANCHOR-NNN` 属主进程锚点构建器（`03` §6.7；INV-4 越界用 `FR-ANCHOR-004`），sidecar **不得**返回；若 sidecar 输出导致主进程 INV 校验失败，主进程按 `03` §6.7 抛 `FR-ANCHOR-00x`，sidecar 原始响应仅作诊断留档。`FR-PARSE-001..012` 的文案、级别、重试语义一律以 `11-error-handling.md` §3.2 为准，本表不得覆盖；`FR-PARSE-013..017` 必须补登记后方可合并（DoD 第 6 条）。

---

## 10. 测试要求

### 10.1 单测（协议层，pytest + 假引擎）

| # | 用例 | 断言 |
|---|---|---|
| T-P1 | `GET /v1/health` 无 token | `200`，`engines` 含 4 个名字 |
| T-P2 | 各端点缺 token / 错 token / 带 `Origin` | `401`/`401`/`403`，`code=FR-PARSE-014` |
| T-P3 | 坐标换算（4 引擎 × 4 旋转 × 2 原点） | 输出 pt、顶左、3 位小数；已知输入 → 已知输出的表驱动断言 |
| T-P4 | `BlockType` 映射 | 14 个目标类型各 ≥ 1 条原始标签；未识别标签 → `text`，`score=0.5` |
| T-P5 | `score` 赋值 | 模型 `0.9`、启发式 `0.5`、OCR `0.5`、`rule` `0.5/0.65`（表驱动） |
| T-P6 | 状态机 | `queued→running→done`、取消、重复取消幂等、非法迁移 → `FR-PARSE-017` |
| T-P7 | 幂等 | 同 `cacheKey` 两次 `POST` → 同 `jobId`、第二次 `reused:true`，且假引擎调用计数 = 1 |
| T-P8 | 断点续传 | 预置 `blocks.batch-001.json` → 只跑第 2 批；`force:true` → 全部重跑 |
| T-P9 | 请求校验 | 缺字段/多余字段/错类型 → `400` + `FR-PARSE-017`（`additionalProperties:false` 生效） |
| T-P10 | 兼容性 | `schemaVersion` 或 `engineVersion` 不匹配的 `cacheKey` 缓存**不得**复用 |
| T-P11 | 监听地址与端口新鲜性 | socket 绑定 `127.0.0.1`；端口 ≠ 0；重启（含 `degraded` 恢复）后端口与上一实例不同；测试同时断言实现中**不存在**端口缓存文件/配置读取 |
| T-P12 | 只读知识库 | 以只读权限挂载 `library/`，全流程无写失败 |
| T-P13 | 脱敏 | 日志中不出现 token、用户名段、块文本 |

测试替身：`services/parser/tests/fakes/{fake_docling,fake_marker,fake_ocr}.py` 返回固定 `RawBlock[]` 与可控延迟/异常；协议层测试**不得**加载真实模型（CI 无 GPU 且需秒级反馈）。

### 10.2 契约测试

1. 用 `fixtures/golden/` 的 **50 篇**跑 `POST /v1/parse`（期望引擎按 `10-testing.md` 黄金集说明选择）；
2. 每个响应做 JSON Schema 校验：请求体 → `parse-request.schema.json`；任务视图 → `parse-result.schema.json`（其 `result` 经 `$ref` 落到 `doc-anchor-model.schema.json`）；
3. 主进程合成后的 `blocks.json` 必须通过 `doc-anchor-model.schema.json`（INV-9）；
4. 确定性：同篇连续两次解析，`blocks.batch-*.json` 逐字节相同（`03` INV-10）；
5. 校验器：Python `jsonschema`（MIT）、TS `ajv`（MIT）；Schema **单一真源**在 `specs/schemas/`，`services/parser/schemas/` 为构建期拷贝（`plan` §3.2），由 `pnpm gen:check` 校验一致。

### 10.3 故障注入

| # | 注入 | 期望 |
|---|---|---|
| T-F1 | 解析中途 `kill -9` sidecar | 指数退避重启；超 3 次进 `degraded` + 快速模式；知识库无半成品 |
| T-F2 | 引擎卡死（假引擎 `sleep(∞)`） | 单批 > 120 s 无进度 → `FR-PARSE-004`；取消接口生效；进程可回收 |
| T-F3 | sidecar 返回非法 JSON / 缺字段 | 主进程丢弃该响应 → `FR-PARSE-013`，重试 1 次后降级 |
| T-F4 | 磁盘满（写入 ENOSPC） | `FR-PARSE-013`（`details.reason='disk_full'`）；清理 `tmp/` 后可成功重试 |
| T-F5 | 端口占用 / 握手超时 | 握手失败 → 重启；3 次后 `degraded` |
| T-F6 | 出站网络尝试（假引擎调 `requests.get`） | 立即失败 + `parse.network.blocked` 日志 + `FR-PARSE-013`（S7） |
| T-F7 | 路径穿越（`..\..\Windows\win.ini`、UNC、库外绝对路径） | `403` + `FR-PARSE-016`，且无任何文件读取发生 |
| T-F8 | OCR 引擎崩溃 | 回退 Tesseract；两者皆失败 → `FR-PARSE-006`、`retryable=true` |
| T-F9 | 加密 PDF（`/Encrypt` + 空密码） | `422` + `FR-LIB-002`（沿用库级规范码，不自造 `FR-PARSE` 码） |
| T-F10 | 确定性破坏（假引擎两次输出不同） | `FR-PARSE-010`（`fatal`），**不写入** `cache/parser/<cacheKey>/blocks.json` |

### 10.4 性能预算

| 场景 | 预算 | 依据 |
|---|---|---|
| 100 页，`engine=docling` | ≤ **60 s**（草稿机 4 核/16 GB/无独显，模型已缓存，冷启动不计入） | 本文件；M2 验收 |
| 100 页，`engine=rule`（主进程纯 JS，含锚点构建） | ≤ **2.5 s** | `03` §11 |
| sidecar 冷启动 + 握手 | ≤ **1500 ms**（`BUDGETS.SIDECAR_HEALTH_MS`；`plan` ADR-04 要求 ≤ 1.5 s） | `00-conventions.md` §9 |
| health/进度轮询单次开销 | ≤ 5 ms | — |
| 100 页 sidecar 内存峰值增量 | ≤ 1200 MB | `BUDGETS.MEMORY_PEAK_MB` |
| OCR 单页 | ≤ 20 s；100 页扫描件 ≤ 8 min | §6.4 |

上表所有阈值必须在 `10-testing.md` 建立指标卡。新增常量（`SIDECAR_HANDSHAKE_MS`、`SIDECAR_HEALTH_INTERVAL_MS`、`SIDECAR_IDLE_TTL_MS`、`SIDECAR_SHUTDOWN_MS`、`SIDECAR_RESTART_MAX`、`SIDECAR_BACKOFF_RESET_MS`、`PARSE_BATCH_PAGES`、`PARSE_JOB_TIMEOUT_MS`、`PARSE_MAX_BODY_BYTES`、`OCR_MAX_PAGE`、`OCR_PAGE_TIMEOUT_MS`、`JOB_RETENTION_MS`）统一放 `packages/core/src/budgets.ts` 与 `services/parser/freeread_parser/constants.py`，两处值必须一致并由 `pnpm gen:check` 校验（禁止散落魔数，`00-conventions.md` §9）。页数上限沿用已有的 `MAX_PAGE_COUNT`（默认 500，`11-error-handling.md` §3.2），本规范不重复定义。

### 10.5 实现落地顺序（给 AI 代理）

1. `packages/parser-protocol/`：由 `specs/schemas/*.json` 生成类型（`pnpm gen`）+ `ParserClient`（握手、健康检查、退避重启、转发 `fr:parser:progress`）；
2. `services/parser/freeread_parser/`：`constants.py` → `http_api.py`（5 端点）→ `jobs.py`（状态机/幂等/续传）→ `coords.py`（§5.1）→ `label_map.py`（§5.4）→ `engines/{docling,marker,grobid,ocr}_adapter.py` → `errors.py`（§9.2）；
3. 主进程 `apps/desktop/src/main/parser-client/`：生命周期编排（§2）、模型下载交互（§7.2）、`rule` 引擎（`03` §6.2/§9）。

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：进程生命周期、5 个 HTTP 端点、`ParseJob` 状态机与幂等/断点续传、4 引擎适配与 14 类 `BlockType` 映射、OCR 通道、模型管理、安全约束、错误码、测试要求 |
| v1.0-r2 | 2026-10-03 | 与同批冻结的相邻规范对齐（仅本文件与两个 schema）：① 错误码表改为**沿用** `11-error-handling.md` §3.2 的 `FR-PARSE-001..012` 语义（禁止改义），协议层新增码顺延为 `FR-PARSE-013..017`，库级错误（加密/过大/格式/缺失）直接复用 `FR-LIB-002/003/004/005`，i18n key 统一为 `errors.FR-<AREA>-NNN`；② `fr:parser:progress` 载荷与 `stage` 取值对齐 `ipc-channels.json` 的 `ParseProgressEvent`，并给出 `ocr` boolean→三态的映射；③ `/v1/health`、`/v1/engines` 增加向 `ParserHealthResponse`/`ParserListEnginesResponse` 的字段映射；④ 页数上限改用已有常量 `MAX_PAGE_COUNT`（默认 500），不再自定义 2000；⑤ §8 S2 明确**端口不复用**（覆盖 `01-architecture.md` §3 的"端口缓存"表述，且不违反 `COLD_START_MS` 预算）。**遗留同步项（需其他规范的维护者处理）**：`FR-PARSE-013..017` 补登记进 `11-error-handling.md` §3.2；§2.2/§10.4 新增常量登记进 `packages/core/src/budgets.ts` 与 `10-testing.md` 指标卡；§4.4 的缓存目录在 `05-storage.md` 的清理策略中对齐 |
