# ADR-0001：采用 Tauri 2 桌面壳 + Python sidecar 核心服务

- 状态：提议
- 日期：2026-10-17

## 背景

FreeRead 需要访问本地 Zotero 数据和 PDF 文件，需要桌面级体验；同时 PDF 版面解析、公式识别、嵌入、RAG 等能力的成熟生态几乎都在 Python。

## 备选方案

1. **Electron + Node 后端**：前端生态成熟；但 Node 端缺少高质量的 PDF 版面解析库，仍需调用 Python。安装包体积大。
2. **Tauri 2 + Python sidecar**：Rust 壳体积小、系统集成好（钥匙串、文件对话框）；Python 进程负责全部核心逻辑。
3. **纯 Python 桌面（PySide6 / Qt）**：单语言；但现代阅读器 UI（KaTeX、图可视化、画布）在 Web 技术栈中实现成本低得多。
4. **Web 应用 + 本地服务**：浏览器打开 localhost；无法很好地处理钥匙串、文件关联、开机自启等。

## 决定

选择方案 2：Tauri 2（Rust）负责窗口与系统集成，React + TypeScript 负责 UI，Python 3.11+ / FastAPI 作为 sidecar 提供核心服务，两者通过 `127.0.0.1` 上的 HTTP + SSE 通信。

## 后果

- 正面：UI 与核心逻辑解耦，Core Service 也可以单独以服务器形式运行，便于测试和将来做 Web 版。
- 负面：需要打包 Python 运行时（PyInstaller 或 python-build-standalone），本地解析模型体积较大，应作为可选下载而不是打进安装包。
- 跟进：M0 阶段验证 Windows 上的 sidecar 打包、启动时间和杀毒软件误报情况。
