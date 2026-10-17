# FreeRead Desktop（Tauri 2 + React + TypeScript）

尚未初始化。M1 开始时在本目录执行：

```bash
npm create tauri-app@latest . -- --template react-ts
```

之后按 [docs/01-architecture.md §7](../../docs/01-architecture.md) 组织 `src/`：

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
