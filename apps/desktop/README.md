# FreeRead Desktop（Tauri 2 + React + TypeScript）

界面采用"纸张、墨色与陶土"设计语言：固定的暖中性色阶 + 一个可选强调色，组件是基于原生元素的小组件，见 [ADR-0007](../../docs/adr/0007-paper-ink-clay-ui.md)。

## 目录

```
src/
├─ app/          App（启动、布局）、store（Zustand：导航、设置、分类、任务推送）、theme（色阶 + 强调色 → CSS 变量）
├─ api/          core（连接 sidecar）、client（openapi-fetch，类型由 OpenAPI 生成）、sse（fetch 读 SSE）、ir（IR 类型）
├─ components/   ui.tsx（按钮、分段控件、开关、选择框、对话框、进度条）、Sidebar（248px 侧栏 / 阅读器 60px 图标栏）、Snackbar、icons
└─ features/
   ├─ library/   分类树、文献列表、同步 / 导入
   ├─ reader/    PdfView（pdf.js）、ReflowView（按 IR 渲染）、locate（双向定位）、render（KaTeX / 表格净化）
   ├─ translate/ useTranslations（已有译文 + 可视区域按需翻译、隐私确认）
   ├─ settings/  外观、翻译、大模型服务与 API Key、解析引擎、隐私
   └─ jobs/      底部任务进度条
```

Rust 壳（`src-tauri/`）：启动 / 关闭 `freeread-core` sidecar（随机端口 + 会话 token，Windows Job Object 兜底清理）、
系统钥匙串保存 API Key 并在启动 sidecar 时注入（`keys.rs`）、文件对话框（`tauri-plugin-dialog`）。

## 开发

```powershell
pwsh scripts/build_sidecar.ps1          # 在仓库根目录执行，生成 src-tauri/binaries/freeread-core-<triple>.exe
cd apps/desktop
npm install
npm run tauri dev                        # 完整桌面应用
npm run tauri build                      # 生成 src-tauri/target/release/bundle/nsis/*-setup.exe
```

只调界面时可以不起 Tauri：手动启动 core，再用浏览器打开 Vite。

```powershell
core/.venv/Scripts/python -m freeread.main --port 8765 --token devtoken --data-dir eval-out/ui-data
# apps/desktop/.env.development.local：
#   VITE_CORE_URL=http://127.0.0.1:8765
#   VITE_CORE_TOKEN=devtoken
npm run dev                              # http://localhost:1420
```

浏览器模式下没有钥匙串和文件对话框：API Key 只在 core 本次运行期间有效，导入 PDF 时手动输入路径。

## 其他命令

```powershell
npm test                                 # Vitest 单元测试
npm run gen:api                          # core 的 API 变化后重新生成 src/api/schema.d.ts
```

`gen:api` 通过 `npx` 临时使用 `openapi-typescript` 与 TypeScript 5（它还不支持本项目的 TypeScript 6），不写进依赖。
