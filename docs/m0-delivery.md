# 交付报告 T-001 / T-006 / T-007

- 状态：M0 工程实现与三平台构建已交付；固定硬件性能验收仍有缺口（规范 10 §4 要求自托管 runner，用户确认当前没有）。
- 规范遵循：00 §2/4/7/8、01 §7、06 §1/2、10 §1/2、11 §1、12 §2/3/5、13 §4；规范修订提交 `77cd83a`、`2dcfe2b`、`92833e6`，取舍见 ADR-13。
- 输出：pnpm/Turbo workspace、TypeScript strict、ESLint/boundaries 与循环依赖门禁、Electron 双语离线空壳、15 份生成契约（74 调用 + 8 事件）、三平台原生打包 CI、完整 AGPL 许可与随包源码、ADR-01–12 落档、10 篇授权 PDF（579 页）。
- 验证证据：`pnpm install --frozen-lockfile`、`pnpm gen`、`pnpm verify`、`pnpm build`、`pnpm size` 通过；3 个 Vitest 文件/5 条用例，3 条 Node 测试，core 实现分支 5/5（100%）；renderer gzip 68.3 KiB；594 个依赖条目通过许可检查，10 篇 PDF 哈希通过。
- 门禁负例：renderer `import fs from 'fs'` 被 no-restricted-imports 拒绝；临时双模块循环被 dependency-cruiser 的 no-circular 拒绝；实际临时安装 SSPL-1.0 依赖时 `pnpm license` 退出 1；手改生成文件时 `pnpm gen:check` 退出 1；许可单测也拒绝其他禁止/未知许可，允许 AGPL。临时探针均已清理，manifest/lock/生成物恢复后冻结安装及 verify 通过。
- 测试内容：AppError 的 wire 往返、cause/stack 剥离、details 冻结与异常兜底；74 个调用的请求/响应校验器一致性、未知字段/空值反例、配置递归 DeepPartial；Electron E2E 检查双语切换、sandbox/contextIsolation、Node 零特权与 preload 白名单，显式 `chromiumSandbox: true` 并断言没有 `--no-sandbox`。Linux/macOS 截图已人工查看。
- 三平台证据：代码提交 `3f601ff` 的 [CI 37045349524](https://github.com/cristimezzz/FreeRead/actions/runs/37045349524) 全绿，包含 Windows NSIS（x64/arm64）及两份 zip、macOS 两架构 dmg/zip、Linux x64 deb/AppImage；均为 M0 未签名开发包。最终提交的执行状态见 [PR checks](https://github.com/cristimezzz/FreeRead/pull/1/checks)。CI 上传安装包、源码归档、构建清单、截图和覆盖率证据。
- 启动证据：上述 CI 无调试器、新用户目录的原生应用进程为 Windows 475 ms、macOS 1247 ms、Linux 478 ms，均小于 2500 ms；这不是固定硬件基准，且测量在 E2E/打包后，操作系统缓存未清空。首次托管 runner 曾测到 macOS 5512 ms、Linux 4303 ms，不能抹去或将各机器结果当作性能回归比较。最终 CI 改为 `pnpm test:cold-start --packaged`，直接启动打包后的本机可执行文件，同样保留 2500 ms 门禁。
- 本机限制：当前 Windows 主机的 Electron GUI 在加载应用前以 `0x80000003` 退出；本机已验证编译与 unpacked 资源，GUI 与 NSIS 完整验证使用成功的原生 Windows CI。包内已检查 LICENSE、第三方清单、SOURCE_OFFER、MODIFICATIONS、build-manifest 和 source.tar.gz；源码归档含中文文件名，排除 .git/node_modules/秘密文件。
- 不声称完成 M1–M6 业务、M2 人工锚点标注/评测、M7 签名与更新；render-reflow 尚无可执行逻辑，覆盖率无分支可计。

## 变更文件

逐文件全文行数（PDF 为字节数；报告本身不计），基线为初始规范提交 `ebbc767`。

| 文件 | 行数 / PDF 字节数 |
|---|---:|
| .dependency-cruiser.cjs | 13 |
| .github/workflows/ci.yml | 74 |
| .github/workflows/license.yml | 32 |
| .gitignore | 58 |
| .npmrc | 2 |
| .prettierignore | 8 |
| .prettierrc.json | 1 |
| apps/cli/package.json | 10 |
| apps/cli/README.md | 3 |
| apps/cli/src/index.ts | 1 |
| apps/cli/tsconfig.json | 10 |
| apps/desktop/e2e/shell.e2e.ts | 43 |
| apps/desktop/electron-builder.yml | 49 |
| apps/desktop/electron.vite.config.ts | 7 |
| apps/desktop/package.json | 24 |
| apps/desktop/src/main/config.generated.ts | 315 |
| apps/desktop/src/main/index.ts | 50 |
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
| docs/adr/ADR-13-m0-gates.md | 12 |
| docs/anchor-model.md | 3 |
| docs/plugin-api.md | 3 |
| eslint.config.mjs | 66 |
| fixtures/golden/index.json | 181 |
| fixtures/golden/jmlr-19-301/attribution.bib | 10 |
| fixtures/golden/jmlr-19-301/paper.pdf | 4716857 |
| fixtures/golden/jmlr-21-0264/attribution.bib | 10 |
| fixtures/golden/jmlr-21-0264/paper.pdf | 782795 |
| fixtures/golden/jmlr-21-1137/attribution.bib | 10 |
| fixtures/golden/jmlr-21-1137/paper.pdf | 2221945 |
| fixtures/golden/jmlr-21-1205/attribution.bib | 10 |
| fixtures/golden/jmlr-21-1205/paper.pdf | 732611 |
| fixtures/golden/jmlr-22-0402/attribution.bib | 10 |
| fixtures/golden/jmlr-22-0402/paper.pdf | 1547072 |
| fixtures/golden/jmlr-22-0687/attribution.bib | 10 |
| fixtures/golden/jmlr-22-0687/paper.pdf | 975672 |
| fixtures/golden/jmlr-22-0801/attribution.bib | 10 |
| fixtures/golden/jmlr-22-0801/paper.pdf | 398300 |
| fixtures/golden/jmlr-22-1120/attribution.bib | 10 |
| fixtures/golden/jmlr-22-1120/paper.pdf | 21978880 |
| fixtures/golden/jmlr-22-1251/attribution.bib | 10 |
| fixtures/golden/jmlr-22-1251/paper.pdf | 1098580 |
| fixtures/golden/jmlr-22-1317/attribution.bib | 10 |
| fixtures/golden/jmlr-22-1317/paper.pdf | 1687646 |
| fixtures/golden/README.md | 18 |
| LICENSE | 661 |
| MODIFICATIONS.md | 3 |
| package.json | 55 |
| packages/agent/package.json | 16 |
| packages/agent/README.md | 5 |
| packages/agent/src/index.ts | 1 |
| packages/agent/tsconfig.json | 13 |
| packages/core/package.json | 19 |
| packages/core/README.md | 6 |
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
| packages/fetch/package.json | 16 |
| packages/fetch/README.md | 5 |
| packages/fetch/src/index.ts | 1 |
| packages/fetch/tsconfig.json | 13 |
| packages/parser-protocol/package.json | 16 |
| packages/parser-protocol/README.md | 5 |
| packages/parser-protocol/src/generated/parse-request.generated.ts | 55 |
| packages/parser-protocol/src/generated/parse-result.generated.ts | 287 |
| packages/parser-protocol/src/index.ts | 2 |
| packages/parser-protocol/tsconfig.json | 13 |
| packages/render-reflow/package.json | 16 |
| packages/render-reflow/README.md | 5 |
| packages/render-reflow/src/index.ts | 1 |
| packages/render-reflow/tsconfig.json | 13 |
| packages/translate/package.json | 16 |
| packages/translate/README.md | 5 |
| packages/translate/src/index.ts | 1 |
| packages/translate/tsconfig.json | 13 |
| packages/ui/package.json | 16 |
| packages/ui/README.md | 5 |
| packages/ui/src/index.ts | 1 |
| packages/ui/tsconfig.json | 13 |
| packages/zotero/package.json | 16 |
| packages/zotero/README.md | 5 |
| packages/zotero/src/index.ts | 1 |
| packages/zotero/tsconfig.json | 13 |
| plan/FreeRead-技术方案与里程碑.md | 631 |
| playwright.config.ts | 6 |
| plugins/README.md | 3 |
| pnpm-lock.yaml | 6257 |
| pnpm-workspace.yaml | 7 |
| README.md | 32 |
| scripts/build-manifest.mjs | 13 |
| scripts/check-fixtures.mjs | 19 |
| scripts/cold-start.mjs | 42 |
| scripts/collect-fixtures.py | 64 |
| scripts/forbid-domains.mjs | 22 |
| scripts/forbid-domains.test.mjs | 7 |
| scripts/gates.test.mjs | 27 |
| scripts/gen.mjs | 114 |
| scripts/license-policy.mjs | 8 |
| scripts/license-policy.test.mjs | 8 |
| scripts/license.mjs | 33 |
| scripts/size.mjs | 7 |
| scripts/source-offer.mjs | 6 |
| services/parser/freeread_parser/__init__.py | 1 |
| services/parser/pyproject.toml | 6 |
| services/parser/README.md | 4 |
| services/parser/schemas/README.md | 3 |
| SOURCE_OFFER.md | 15 |
| specs/00-conventions.md | 187 |
| specs/12-build-release.md | 155 |
| specs/13-task-template.md | 182 |
| specs/README.md | 186 |
| THIRD_PARTY_NOTICES.md | 7757 |
| tsconfig.base.json | 12 |
| tsconfig.json | 35 |
| turbo.json | 4 |
| vitest.config.mjs | 12 |
