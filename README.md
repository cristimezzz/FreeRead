# FreeRead

本地优先、AGPL-3.0 的论文精读工作台。M0 当前交付工程骨架与离线双语空壳；
阅读、翻译、笔记、解析和研究 Agent 按 M1–M6 实现。

不提供云端账号、计费额度或付费墙规避；V1 不包含浏览器自动化抓取。

需要 Node 22.12+ 和 pnpm 11.21.0；Python 仅供后续 sidecar 与维护者采集样本使用。

```sh
pnpm install --frozen-lockfile
pnpm gen
pnpm verify
pnpm dev
pnpm test:e2e
pnpm test:cold-start
pnpm build:dist
```

`pnpm build` 编译，`build:dist` 在当前平台打包。`.github/workflows/ci.yml` 在三个原生
runner 上分别产出 NSIS/zip、dmg/zip、deb/AppImage；M0 包未签名，M7 再做签名与发布。
当前命令不提供尚未实现的锚点评测、sidecar 构建或业务 CLI。

契约真源在 [specs](specs/README.md)，运行 `pnpm gen` 生成类型、preload 白名单、
IPC 注册清单与校验器，`gen:check` 拒绝生成漂移。未实现的业务通道不注册 handler。
renderer 无 Node 特权，空壳运行时出网被 CSP 与 Electron session 拦截。

许可门禁检查全部已安装依赖（含开发依赖）；`pnpm license check <pkg>` 可在引入前
核验。所有安装包随附许可、第三方清单、构建清单和对应源码 `source.tar.gz`。
首批授权论文见 [fixtures/golden](fixtures/golden/README.md)。

[M0 交付报告](docs/m0-delivery.md) 记录实际验收、安装包证据及固定硬件基准缺口。
