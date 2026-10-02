# 交付报告 T-001 / T-006 / T-007

- 状态：实现完成，本地 verify 通过；三平台 CI 与安装包验收进行中。
- 规范遵循：00 §2/4/7/8、01 §7、06 §1/2、10 §1/2、11 §1、12 §2/3/5、13 §4；规范修订提交 `77cd83a`、`2dcfe2b`、`92833e6`，取舍见 ADR-13。
- 输出：pnpm/Turbo workspace、TypeScript strict、ESLint/boundaries 与循环依赖门禁、Electron 双语离线空壳、15 份生成契约（74 调用 + 8 事件）、三平台原生打包 CI、完整 AGPL 许可与随包源码、ADR-01–12 落档、10 篇授权 PDF（579 页）。
- 验证证据：`pnpm gen`、`pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm gen:check`、`pnpm license`、`pnpm forbid`、`pnpm fixtures:check` 通过；3 个 Vitest 文件/5 条用例，3 条 Node 测试，core 实现分支 5/5（100%）；renderer gzip 111.4 KiB。
- 门禁负例：renderer `import fs from 'fs'` 被 no-restricted-imports 拒绝；临时双模块循环被 dependency-cruiser 的 no-circular 拒绝；许可测试拒绝 SSPL/BUSL/Elastic/GPL-2.0-only/UNLICENSED/专有/CC-BY-NC/未知许可，允许 AGPL。临时探针均已清理。
- 测试内容：AppError 的 wire 往返、cause/stack 剥离、details 冻结与异常兜底；74 个调用的请求/响应校验器一致性、未知字段/空值反例、配置递归 DeepPartial；Electron E2E 检查双语切换、冷启动 2500 ms、sandbox/contextIsolation、Node 零特权与 preload 白名单。
- 本机限制：Windows 下 Electron GUI 进程在加载应用前以 `0x80000003` 退出；普通独立启动也失败，禁用 GPU 未解决。本地 E2E 尚未通过，待 GitHub 原生 runner 实测；未放宽 sandbox 或冷启动阈值。
- 不声称完成 M1–M6 业务、M2 人工锚点标注/评测、M7 签名与更新；render-reflow 尚无可执行逻辑，覆盖率无分支可计。

## 变更文件

完整逐文件清单（文本为行数，PDF 为字节数）由下表记录。

| 文件 | 行数 / PDF 字节数 |
|---|---:|
| .dependency-cruiser.cjs | 13 |
| .github/workflows/ci.yml | 53 |
| .github/workflows/license.yml | 31 |
| .npmrc | 2 |
| .prettierignore | 8 |
| .prettierrc.json | 1 |
| LICENSE | 661 |
| MODIFICATIONS.md | 3 |
| README.md | 31 |
| SOURCE_OFFER.md | 15 |
| THIRD_PARTY_NOTICES.md | 7757 |
| apps/cli/README.md | 3 |
| apps/cli/package.json | 10 |
| apps/cli/src/index.ts | 1 |
| apps/cli/tsconfig.json | 10 |
| apps/desktop/e2e/shell.e2e.ts | 43 |
| apps/desktop/electron-builder.yml | 45 |
| apps/desktop/electron.vite.config.ts | 7 |
| apps/desktop/package.json | 23 |
| apps/desktop/src/main/config.generated.ts | 315 |
| apps/desktop/src/main/index.ts | 42 |
| apps/desktop/src/main/ipc/contract-data.generated.ts | 2 |
| apps/desktop/src/main/ipc/registry.generated.ts | 1338 |
| apps/desktop/src/main/ipc/schemas.contract.test.ts | 20 |
| apps/desktop/src/main/ipc/schemas.generated.ts | 78 |
| apps/desktop/src/main/ipc/validate.ts | 26 |
| apps/desktop/src/preload/bridge.generated.ts | 111 |
| apps/desktop/src/preload/index.ts | 1 |
| apps/desktop/src/renderer/i18n/en.json | 7 |
| apps/desktop/src/renderer/i18n/zh-CN.json | 7 |
| apps/desktop/src/renderer/index.html | 10 |
| apps/desktop/src/renderer/ipc/client.generated.ts | 114 |
| apps/desktop/src/renderer/main.tsx | 25 |
| apps/desktop/src/renderer/shell.css | 9 |
| apps/desktop/tsconfig.json | 20 |
| docs/adr/ADR-01.md | 11 |
| docs/adr/ADR-02.md | 9 |
| docs/adr/ADR-03.md | 9 |
| docs/adr/ADR-04.md | 22 |
| docs/adr/ADR-05.md | 8 |
| docs/adr/ADR-06.md | 8 |
| docs/adr/ADR-07.md | 7 |
| docs/adr/ADR-08.md | 8 |
| docs/adr/ADR-09.md | 7 |
| docs/adr/ADR-10.md | 12 |
| docs/adr/ADR-11.md | 11 |
| docs/adr/ADR-12.md | 15 |
| docs/anchor-model.md | 3 |
| docs/m0-delivery.md | 14 |
| docs/plugin-api.md | 3 |
| eslint.config.mjs | 66 |
| fixtures/golden/README.md | 18 |
| fixtures/golden/index.json | 181 |
| fixtures/golden/jmlr-19-301/attribution.bib | 9 |
| fixtures/golden/jmlr-19-301/paper.pdf | 4716857 |
| fixtures/golden/jmlr-21-0264/attribution.bib | 9 |
| fixtures/golden/jmlr-21-0264/paper.pdf | 782795 |
| fixtures/golden/jmlr-21-1137/attribution.bib | 9 |
| fixtures/golden/jmlr-21-1137/paper.pdf | 2221945 |
| fixtures/golden/jmlr-21-1205/attribution.bib | 9 |
| fixtures/golden/jmlr-21-1205/paper.pdf | 732611 |
| fixtures/golden/jmlr-22-0402/attribution.bib | 9 |
| fixtures/golden/jmlr-22-0402/paper.pdf | 1547072 |
| fixtures/golden/jmlr-22-0687/attribution.bib | 9 |
| fixtures/golden/jmlr-22-0687/paper.pdf | 975672 |
| fixtures/golden/jmlr-22-0801/attribution.bib | 9 |
| fixtures/golden/jmlr-22-0801/paper.pdf | 398300 |
| fixtures/golden/jmlr-22-1120/attribution.bib | 9 |
| fixtures/golden/jmlr-22-1120/paper.pdf | 21978880 |
| fixtures/golden/jmlr-22-1251/attribution.bib | 9 |
| fixtures/golden/jmlr-22-1251/paper.pdf | 1098580 |
| fixtures/golden/jmlr-22-1317/attribution.bib | 9 |
| fixtures/golden/jmlr-22-1317/paper.pdf | 1687646 |
| package.json | 54 |
| packages/agent/README.md | 5 |
| packages/agent/package.json | 16 |
| packages/agent/src/index.ts | 1 |
| packages/agent/tsconfig.json | 13 |
| packages/core/README.md | 6 |
| packages/core/package.json | 19 |
| packages/core/src/agent/permissions.generated.ts | 23 |
| packages/core/src/agent/session.generated.ts | 95 |
| packages/core/src/anchor.generated.ts | 170 |
| packages/core/src/annotation.generated.ts | 173 |
| packages/core/src/budgets.test.ts | 7 |
| packages/core/src/budgets.ts | 13 |
| packages/core/src/error.test.ts | 23 |
| packages/core/src/error.ts | 44 |
| packages/core/src/index.ts | 11 |
| packages/core/src/ipc-channels.generated.ts | 5 |
| packages/core/src/ipc-payloads.generated.ts | 4570 |
| packages/core/src/meta.generated.ts | 135 |
| packages/core/tsconfig.json | 13 |
| packages/fetch/README.md | 5 |
| packages/fetch/package.json | 16 |
| packages/fetch/src/index.ts | 1 |
| packages/fetch/tsconfig.json | 13 |
| packages/parser-protocol/README.md | 5 |
| packages/parser-protocol/package.json | 16 |
| packages/parser-protocol/src/generated/parse-request.generated.ts | 55 |
| packages/parser-protocol/src/generated/parse-result.generated.ts | 287 |
| packages/parser-protocol/src/index.ts | 2 |
| packages/parser-protocol/tsconfig.json | 13 |
| packages/render-reflow/README.md | 5 |
| packages/render-reflow/package.json | 16 |
| packages/render-reflow/src/index.ts | 1 |
| packages/render-reflow/tsconfig.json | 13 |
| packages/translate/README.md | 5 |
| packages/translate/package.json | 16 |
| packages/translate/src/index.ts | 1 |
| packages/translate/tsconfig.json | 13 |
| packages/ui/README.md | 5 |
| packages/ui/package.json | 16 |
| packages/ui/src/index.ts | 1 |
| packages/ui/tsconfig.json | 13 |
| packages/zotero/README.md | 5 |
| packages/zotero/package.json | 16 |
| packages/zotero/src/index.ts | 1 |
| packages/zotero/tsconfig.json | 13 |
| playwright.config.ts | 6 |
| plugins/README.md | 3 |
| pnpm-lock.yaml | 6257 |
| pnpm-workspace.yaml | 7 |
| scripts/build-manifest.mjs | 13 |
| scripts/check-fixtures.mjs | 19 |
| scripts/collect-fixtures.py | 64 |
| scripts/forbid-domains.mjs | 22 |
| scripts/forbid-domains.test.mjs | 7 |
| scripts/gates.test.mjs | 27 |
| scripts/gen.mjs | 114 |
| scripts/license-policy.mjs | 8 |
| scripts/license-policy.test.mjs | 8 |
| scripts/license.mjs | 33 |
| scripts/size.mjs | 7 |
| scripts/source-offer.mjs | 7 |
| services/parser/README.md | 4 |
| services/parser/freeread_parser/__init__.py | 1 |
| services/parser/pyproject.toml | 6 |
| services/parser/schemas/README.md | 3 |
| tsconfig.base.json | 12 |
| tsconfig.json | 35 |
| turbo.json | 4 |
| vitest.config.mjs | 12 |
| .gitattributes | 30 |
| .gitignore | 58 |
| docs/adr/ADR-13-m0-gates.md | 11 |
