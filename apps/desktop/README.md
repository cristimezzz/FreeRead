# FreeRead Desktop（Tauri 2 + React + TypeScript）

M0 阶段已用 `npm create tauri-app@latest . -- --template react-ts` 初始化，目前只包含 sidecar 验证所需的最小实现（见 [docs/m0-tauri-sidecar.md](../../docs/m0-tauri-sidecar.md)）：

- `src-tauri/src/lib.rs`：绑定 `127.0.0.1:0` 取空闲端口、生成 256 位随机 token，通过 `tauri-plugin-shell` 的 `externalBin` 启动
  `freeread-core --port <p> --token <t> --parent-pid <壳 PID>`；`RunEvent::Exit` 时结束 sidecar。
- `src-tauri/src/job.rs`：Windows 上把 sidecar 放进 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 的 Job Object，壳崩溃 / 被强杀时由系统清理。
- `src/App.tsx`：通过 `core_info` 命令拿到端口和 token，带 `X-FreeRead-Token` 头轮询 `/health` 并显示结果。

## 构建

```powershell
pwsh scripts/build_sidecar.ps1          # 在仓库根目录执行，生成 src-tauri/binaries/freeread-core-<triple>.exe
cd apps/desktop
npm install
npm run tauri dev                        # 开发
npm run tauri build                      # 生成 src-tauri/target/release/bundle/nsis/*-setup.exe
```

## 之后（M1）

按 [docs/01-architecture.md §7](../../docs/01-architecture.md) 组织 `src/`：

```
src/
├─ app/          路由、布局、全局 Provider
├─ api/          openapi-typescript 生成的类型 + fetch / SSE 客户端
├─ features/{library,reader,translate,summary,graph}/
├─ stores/       Zustand
└─ components/
```

主要依赖：`pdfjs-dist`、`katex`、`dompurify`、`zustand`、`@xyflow/react`（问答画布）、`cytoscape`（图谱浏览）。

Rust 壳职责：启动 / 关闭 `freeread-core` sidecar（传入随机端口与会话 token）、从系统钥匙串读取 API Key 并注入 sidecar 环境变量、文件对话框。
