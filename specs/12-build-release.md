# 12 · 构建、发布与许可合规

> 状态：**冻结**。主仓 **AGPL-3.0**（见方案 §12.1）——本文件同时是**许可义务的执行手册**。

---

## 1. 版本与标识

| 标识 | 规则 | 示例 |
|---|---|---|
| 应用版本 | SemVer `MAJOR.MINOR.PATCH`，由 `changesets` 管理 | `0.1.0` |
| 构建号 | `YYYYMMDD.<run_number>`（CI 注入 `BUILD_ID`） | `20261003.41` |
| 数据格式版本 | `schemaVersion`（锚点/meta/annotation/config 各自独立，见 `specs/schemas`） | `1` |
| 解析规则版本 | `PARSER_RULES_REVISION`（构建期常量，规则改动 +1；参与缓存键） | `7` |
| IPC API 版本 | `apiVersion`（`schemas/ipc-channels.json`） | `1` |

**禁止**在代码中硬编码版本号；统一从 `packages/core/src/version.ts`（由构建注入）读取。

---

## 2. 构建

```bash
pnpm install --frozen-lockfile
pnpm gen            # schemas → *.generated.ts
pnpm verify         # typecheck + lint + test + boundary + license + forbid
pnpm build          # 编译所有包（tsc --build）
pnpm build:dist     # 打包三平台产物（electron-builder）
pnpm build:sidecar  # 构建 Python sidecar（PyInstaller，仅 release 通道）
```

**环境要求**：Node ≥ 20（`engines` 强制）、pnpm ≥ 9、Python 3.11（仅构建 sidecar 时）。**锁定依赖**：提交 `pnpm-lock.yaml`，CI 使用 `--frozen-lockfile`。

**可复现性**：CI 记录 `SOURCE_DATE_EPOCH`；构建产物写入 `build-manifest.json`（含各包 git sha、依赖锁 hash、Node/Python 版本、构建机标识）。

---

## 3. 产物矩阵

| 平台 | 格式 | 目标体积 | 是否内置 sidecar |
|---|---|---|---|
| Windows x64/arm64 | NSIS 安装包 + portable zip | ≤ 260 MB / ≤ 600 MB（含 sidecar） | 否（首次启用重排时下载） |
| macOS x64/arm64 | dmg + zip（签名 + 公证） | 同上 | 否 |
| Linux x64 | `.deb` + AppImage | 同上 | 否 |
| sidecar 运行时 | 按平台的归档包（含 Python 运行时与依赖） | 150–300 MB | — |
| 模型包 | 按需下载（OCR/版面模型），SHA256 校验 | 视模型 | — |

**分发原则**：应用**默认不含**模型与 sidecar 运行时；首次启用重排/OCR 时弹窗说明体积与用途，用户确认后下载（`fr:parser:consentModelDownload`）。这条同时降低了主包体积与许可审计复杂度。

---

## 4. 签名与更新

| 项 | 要求 |
|---|---|
| Windows | EV/OV 代码签名证书；`signtool` 签名 exe 与安装包；更新包必须签名 |
| macOS | Developer ID + `notarytool` 公证；`hardenedRuntime` 开启；entitlements 最小化 |
| Linux | 提供 `.deb` 的 GPG 签名与 AppImage 的 sha256 |
| 自动更新 | `electron-updater`，源可配置（默认官方 CDN）；**校验签名后安装**；支持关闭自动更新 |
| 通道 | `stable` / `beta`；beta 通过 `config.json` 的 `updateChannel` 切换 |
| 回滚 | 每个通道保留最近 3 个版本；`latest.yml` 可回指旧版本实现软回滚；重大故障发布"回滚说明"issue |

**更新失败降级**：更新失败不得影响应用可用性；错误码 `FR-SYS-*`（见 `11-error-handling.md`）。

---

## 5. 许可合规产物（随每个发布包）

| 产物 | 内容 | 生成方式 |
|---|---|---|
| `LICENSE` | AGPL-3.0 全文 | 仓库根 |
| `THIRD_PARTY_NOTICES.md` | 全部第三方依赖（JS + Python + 模型权重）名称/版本/许可/版权行 | `pnpm license:notices` |
| `SOURCE_OFFER.md` | **AGPL 源码义务**：说明如何获取对应源码（含 sidecar 依赖的源码获取方式与脚本），并声明修改过的第三方文件及修改点 | `pnpm license:source-offer` 生成模板 + 人工补全 |
| `sidecar-deps.json` | Python 依赖清单（`pip freeze` 快照 + 许可字段） | `services/parser/scripts/gen_deps.py` |
| `models.json` | 模型清单（名称、来源 URL、许可、SHA256） | 手工维护，CI 校验字段完整 |
| `MODIFICATIONS.md` | 我们对第三方源码的修改清单（若 vendor 了任何代码） | 手工 + CI 提醒 |

**License Gate 黑名单**（CI 强制，命中即失败）：`SSPL-1.0`、`BUSL-1.1`、`Elastic-2.0`、`GPL-2.0-only`、`UNLICENSED`、任何专有许可、**CC-BY-NC 类模型权重**（如 Nougat 权重）。
**允许**：AGPL-3.0、GPL-3.0、LGPL、MIT、Apache-2.0、BSD、ISC、MPL-2.0、CC0、Unlicense、OFL（字体）。

**AGPL 三条义务的落地检查**（`scripts/check-agpl-obligations.sh`）：

1. 发布包内包含 `SOURCE_OFFER.md` 且其链接可达（指向对应 tag 的源码归档）；
2. 若提供**网络服务**（当前 V1 无；V2 云同步上线前必须复核）：服务界面须提供源码获取入口；
3. 修改过的第三方文件必须在 `MODIFICATIONS.md` 登记，并在该文件头注明"modified by FreeRead"。

---

## 6. 发布检查清单（Release Checklist）

发布前逐项勾选，缺一不可：

- [ ] `pnpm verify` 全绿（含 License Gate 与禁用域名门禁）
- [ ] 全集锚点评测 P0 指标达标（F1 ≥ 0.90 / IoU ≥ 0.98 / 覆盖率 100% / 确定性 100%）
- [ ] 全量 E2E（15 条）通过，无 flaky
- [ ] 性能基准达标（首屏/冷启动/内存/滚动）
- [ ] `THIRD_PARTY_NOTICES.md`、`SOURCE_OFFER.md`、`sidecar-deps.json`、`models.json` 已更新且随包
- [ ] `MODIFICATIONS.md` 与实际 vendor 情况一致
- [ ] 三平台产物签名验证通过（Windows/macOS/Linux）
- [ ] 升级路径测试：上一 stable 版本 → 本版本，配置与知识库无损坏
- [ ] 降级路径测试：本版本 → 上一 stable 版本（数据可读，`doctor` 无错误）
- [ ] `schemaVersion` 变更时提供迁移且迁移测试通过
- [ ] `CHANGELOG.md` 已按 changesets 生成并人工润色（含"数据格式变更"小节）
- [ ] 隐私声明更新（若新增任何出站请求或本地采集）
- [ ] `specs/` 相关文件状态与变更记录已更新
- [ ] 发布说明含：新增能力、已知问题、**许可与合规声明**

---

## 7. CI/CD 工作流

```yaml
# .github/workflows/release.yml（要点）
on: { push: { tags: ['v*'] } }
jobs:
  verify:    { steps: [pnpm verify, eval:anchor --set golden, e2e --smoke] }
  build:     { strategy: { matrix: { os: [windows-latest, macos-latest, ubuntu-latest] } },
               steps: [pnpm build:dist, pnpm license:notices, pnpm license:source-offer] }
  sign:      { needs: build, steps: [sign-all-artifacts, verify-signatures] }
  sidecar:   { steps: [pnpm build:sidecar, upload-runtime-archive] }   # 独立产物，不打进主包
  publish:   { needs: [sign, sidecar], steps: [gh-release, upload-latest-yml, update-channels] }
```

---

## 8. 隐私与遥测

| 项 | 默认 | 说明 |
|---|---|---|
| 遥测 / 埋点 | **关闭** | 无任何分析 SDK；如需统计只能本地聚合、用户可导出 |
| 崩溃上报 | **关闭**（opt-in） | 若用户开启，上传前脱敏（去掉路径、笔记、译文、密钥）；拒绝任何第三方广告 SDK |
| 网络请求 | 仅 NetGuard 白名单 | 见 `09-fetch-compliance.md` |
| 本地数据 | 全在用户磁盘 | 无账号、无云端；`library` 目录可整体迁移 |

**发布说明中必须声明**：本应用不含广告 SDK、不上传用户文档、不设服务器账号。

---

## 9. 热修复流程

1. 从发布 tag 拉 `hotfix/<version>` 分支；
2. 只允许最小修复 + 回归测试；**禁止**夹带功能；
3. 走"精简版检查清单"（verify + 相关 E2E + 签名 + NOTICE 未变）；
4. 发布 `PATCH` 版本并在 CHANGELOG 标注 `Security`/`Critical`；
5. 24 h 内补一份事故说明（根因 + 防复发措施 + 新增测试用例）。

---

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结（AGPL-3.0 义务落地） |
