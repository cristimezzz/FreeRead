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

### M0 实测（2026-10-17，Windows 11，数据见 [m0-tauri-sidecar.md](../m0-tauri-sidecar.md)）

- **打包可行**：PyInstaller 打包 core（不含解析引擎）+ Tauri `externalBin` + NSIS，安装包 17.56 MiB，安装后 21.7 MB；静默安装、启动、界面拿到 `/health` = ok 全部正常。
- **启动时间**：sidecar 热启动到 `/health` 可用，onefile 约 3.06 s，onedir 约 1.04 s（各 5 次中位数）。用户能感知到的壳启动到界面就绪约 2.6 s（onefile）。冷启动（新文件，含杀毒软件首次扫描）7–13 s。
- **进程清理可靠**：`RunEvent::Exit` 主动结束、`KILL_ON_JOB_CLOSE` 的 Job Object、sidecar 的 `--parent-pid` 看门狗三道保险。正常关闭和 `taskkill /F` 强杀壳各 5 次，都没有残留 `freeread-core`（0.1–0.4 s 内清理完）。onefile 下真正的 Python 进程是引导进程的子进程，只 kill 引导进程会留下孤儿，所以 Job Object 是必需的，不能省。
- **杀毒软件是主要风险**：按需扫描 0 检出，但 Kaspersky 的主动防御把无签名的新 exe 归入"低限制"组，导致过安装静默失败（退出码仍为 0）、壳启动 `拒绝访问`、onefile 无法解压到 `%TEMP%`；构建期 `cookie` 的构建脚本还被误报为木马。
- **由此调整的决定**：
  - 发布形态从 onefile 改为 **PyInstaller onedir**：启动快约 2 s，运行时不写 `%TEMP%`，更不容易被拦截。实现方式是 exe 作为 `externalBin`、`_internal/` 作为 `bundle.resources`。M0 验证仍用 onefile，M1 切换。
  - 首个对外发布版本之前必须完成 **Authenticode 代码签名**（壳、sidecar、安装包）。
  - 前端通过 CORS 直连 sidecar（只放行 Tauri 源），保持"前端直接 HTTP + SSE"的架构，不经过 Rust 转发。
