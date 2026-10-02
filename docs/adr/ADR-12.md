# ADR-12 工程与发布 ✅

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

| 项 | 选择 | 许可 |
|---|---|---|
| 包管理与 monorepo | pnpm workspaces + Turborepo | MIT |
| 测试 | Vitest（单测）+ Playwright（Electron E2E） | MIT / Apache |
| 代码规范 | ESLint + Prettier + TypeScript strict + `eslint-plugin-boundaries`（模块边界） | MIT |
| 打包 | electron-builder（NSIS / dmg / deb / AppImage） | MIT |
| 自动更新 | electron-updater（**仅签名包**；更新源可配置） | MIT |
| 崩溃上报 | **默认关闭**；启用时用 Sentry 自托管或完全关闭（隐私优先） | MIT（自托管） |
| CI | GitHub Actions：typecheck / test / e2e / **License Gate** / 打包 | — |
| **License Gate** | `license-checker-rsc` + **黑名单**：`SSPL`、`BUSL-1.1`、`Elastic-2.0`、`GPL-2.0-only`（与 AGPLv3 不兼容）、任何 `UNLICENSED`/专有依赖、以及 **CC-BY-NC 类模型权重**（如 Nougat 权重）一律 fail；AGPL/GPLv3/MIT/Apache 允许。同时生成 `THIRD_PARTY_NOTICES.md` 与 `SOURCE_OFFER.md`（AGPL 源码义务） | — |
