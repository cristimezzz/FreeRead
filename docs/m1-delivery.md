# 交付报告 T-008 / T-009 / T-003

- 状态：M1 实现与本地质量门禁已交付；Electron 原生 E2E / 强杀 20 次及固定硬件性能验收待原生 CI 验证，暂不声称 M1 全部验收完成。
- 规范遵循：00 §2/4/7/8、01 §1/4、02 §3.2、05 §1/4/7/11、06 §2/5、07 §1/3/5、10 E2/E4/E6/E11/E14/E15、13 §5。规范提交 `252e2e9`；ADR-14 解决进度真源冲突，meta schemaVersion 2，并提供 v1 迁移。锚点 schema 保持 1。
- 输出：授权文件选择、worker PDF 提取、sha256 去重、原子目录发布、标签、同一中文分词函数支持 FTS5 标题/摘要/正文；SQLite WAL 可重建及损坏保留；原文可视页 canvas、PDF.js textLayer、选择高亮/笔记/书签、追加标注与墓碑、Markdown；句子即时同步原子保存与 OpLogEntry 启动补偿、页码回退与可见降级。
- 验证证据：`pnpm verify` 通过（17 个单元/集成用例 + 3 个 Node 门禁用例，core 44/44 分支、62/62 语句）；默认跳过需 Edge 的补充预览，用 `FR_UI_PREVIEW=1` 单独实跑成功。17 份生成物一致；597 个依赖许可条目通过；10 篇授权 PDF 哈希通过。补充集成断言：文献目录被外部 junction 替换后，标注/Markdown 写入均拒绝。
- `pnpm build`、`pnpm size` 通过；renderer + PDF worker gzip 合计约 574 KiB。PDF.js 是规范指定的阅读引擎（Apache-2.0，安装前 `pnpm license check pdfjs-dist` 通过）；其体积超过普通前端组件阈值，因为包含实际 PDF 解释器与隔离 worker。未引入 SQLite 原生模块、路由库或虚拟列表库；库用 50 条分页、阅读器只渲染可视页。
- 真实 PDF 提取：授权样本 `jmlr-22-0801` 27 页 / 10875 个最小文本句段，worker 成功；不宣称这些基础块满足 M2 的版面指标。
- 补充浏览器证据：Edge 154.0.4258.48、真实 PDF worker 和真实 SQLite/文件服务，生成 1000 页文本 PDF；首屏 1151 ms、10 秒滚动约 120.08 fps、canvas ≤ 5。截图位于 `test-results/m1-{library,reader}-browser.png`，测量 JSON `test-results/m1-browser-performance.json`。此预览只为本地 QA 放行同源 HTTP，发布应用仍仅 `fr-file:`；不能等同 Electron、复杂真实 PDF 或固定硬件正式性能门禁。
- 新增测试：确定性/字符覆盖/非法输入、句子缺失与页码越界、v1 迁移、CJK 分词对称、去重与源 PDF 字节不变、删除 SQLite 后精确恢复、文件不可写时日志补偿、标注损坏/断尾后继续追加、墓碑、Markdown、SQLite 损坏重建、路径及会话越界。原生 E2E 新增 5 次精确恢复、笔记重启、20 次强杀与 1000 页性能断言，阈值未降低。
- 本机限制：`pnpm exec playwright test` 的 Electron 在窗口出现前报 `Process failed to launch`，与 M0 主机限制一致；实际执行失败已记录，不把待执行原生用例计为通过。
- 原生 CI 首轮：[run 37054125574](https://github.com/cristimezzz/FreeRead/actions/runs/37054125574) 三平台 verify/build/size 通过，但 E2E 界面消失后超时；正通过进程退出与 renderer 错误日志定位，不计为验收通过。草稿 [PR #2](https://github.com/cristimezzz/FreeRead/pull/2) 以尚未合并的 M0 分支为基线。
- 未决：固定硬件 runner 未配置；原生三平台 / ARM64 包运行待验证；M2 版面解析、OCR、重排及 M3–M7 功能不在此次范围。

## 变更文件

下表按目录归并；逐文件行数见末尾清单。

| 范围 | 内容 |
|---|---|
| `packages/core/src/{anchor,progress,search,storage}` | 最小阅读模型、纯位置恢复、迁移、citekey、中文分词、由规范生成的 DDL、测试 |
| `apps/desktop/src/main/{infra,services,ipc}` | 文件原子操作、本地 PDF Range 协议、SQLite、库/笔记/阅读服务、worker、严格 IPC、集成测试 |
| `apps/desktop/src/renderer` | 原文阅读器、文献库、笔记面板、双语文案、响应式布局 |
| `apps/desktop/e2e` | 原始合成 PDF、原生功能/崩溃/性能用例 |
| `specs/`、`docs/adr/ADR-14-m1-reading.md` | M1 卡片、进度真源修订及 schema v2 |
| 依赖/生成器/许可产物 | PDF.js、冻结锁文件、生成 DDL/preload、本地许可清单 |

| 文件 | 全文行数 |
|---|---:|
| `AGENTS.md` | 131 |
| `README.md` | 35 |
| `THIRD_PARTY_NOTICES.md` | 7799 |
| `apps/desktop/e2e/pdf-fixture.ts` | 21 |
| `apps/desktop/e2e/reader.e2e.ts` | 86 |
| `apps/desktop/e2e/shell.e2e.ts` | 44 |
| `apps/desktop/electron.vite.config.ts` | 9 |
| `apps/desktop/package.json` | 26 |
| `apps/desktop/src/main/index.ts` | 76 |
| `apps/desktop/src/main/infra/config.ts` | 21 |
| `apps/desktop/src/main/infra/files.ts` | 73 |
| `apps/desktop/src/main/infra/index-store.ts` | 92 |
| `apps/desktop/src/main/infra/pdf-protocol.ts` | 42 |
| `apps/desktop/src/main/ipc/contract-data.generated.ts` | 3 |
| `apps/desktop/src/main/ipc/handlers.ts` | 113 |
| `apps/desktop/src/main/ipc/validate.ts` | 33 |
| `apps/desktop/src/main/services/extract.ts` | 27 |
| `apps/desktop/src/main/services/library-service.test.ts` | 113 |
| `apps/desktop/src/main/services/library-service.ts` | 167 |
| `apps/desktop/src/main/services/note-service.ts` | 122 |
| `apps/desktop/src/main/services/pdf-worker.ts` | 33 |
| `apps/desktop/src/main/services/preview.test.ts` | 95 |
| `apps/desktop/src/main/services/reader-service.ts` | 39 |
| `apps/desktop/src/preload/bridge.generated.ts` | 113 |
| `apps/desktop/src/renderer/env.d.ts` | 2 |
| `apps/desktop/src/renderer/i18n/en.json` | 84 |
| `apps/desktop/src/renderer/i18n/text.ts` | 8 |
| `apps/desktop/src/renderer/i18n/zh-CN.json` | 84 |
| `apps/desktop/src/renderer/index.html` | 11 |
| `apps/desktop/src/renderer/ipc/api.ts` | 22 |
| `apps/desktop/src/renderer/ipc/client.generated.ts` | 116 |
| `apps/desktop/src/renderer/main.tsx` | 28 |
| `apps/desktop/src/renderer/shell.css` | 24 |
| `apps/desktop/src/renderer/views/LibraryView.tsx` | 66 |
| `apps/desktop/src/renderer/views/NotesPanel.tsx` | 31 |
| `apps/desktop/src/renderer/views/OriginalPane.tsx` | 60 |
| `apps/desktop/src/renderer/views/PdfPage.tsx` | 68 |
| `apps/desktop/src/renderer/views/ReaderView.tsx` | 83 |
| `apps/desktop/src/renderer/views/use-reader.ts` | 92 |
| `docs/adr/ADR-14-m1-reading.md` | 18 |
| `packages/core/src/anchor/m1-model.ts` | 47 |
| `packages/core/src/index.ts` | 17 |
| `packages/core/src/ipc-payloads.generated.ts` | 4581 |
| `packages/core/src/meta.generated.ts` | 146 |
| `packages/core/src/progress/resolve.test.ts` | 44 |
| `packages/core/src/progress/resolve.ts` | 22 |
| `packages/core/src/search/segment.ts` | 5 |
| `packages/core/src/storage/citekey.ts` | 14 |
| `packages/core/src/storage/schema.generated.ts` | 3 |
| `packages/core/src/storage/schema.sql` | 118 |
| `pnpm-lock.yaml` | 6392 |
| `scripts/gen.mjs` | 118 |
| `specs/02-domain-model.md` | 197 |
| `specs/05-storage.md` | 558 |
| `specs/06-ipc-contract.md` | 826 |
| `specs/07-ui-spec.md` | 1025 |
| `specs/13-task-template.md` | 192 |
| `specs/README.md` | 188 |
| `specs/schemas/meta.schema.json` | 191 |
