# 开发者指南

FreeRead 由两部分组成：

- **桌面壳**（`apps/desktop`）：Tauri 2（Rust）+ React + TypeScript。负责窗口、系统钥匙串、文件对话框，并启动 / 关闭 Core sidecar（随机端口 + 会话 token，Windows Job Object 兜底清理）。
- **Core Service**（`core`）：Python 3.11+ / FastAPI，作为 sidecar 运行，只监听 `127.0.0.1`。负责 Zotero 连接、PDF 解析与规范化（Document IR）、任务队列、LLM 网关、检索、翻译、总结、问答、批注。数据存 SQLite（Alembic 迁移，FTS5 + sqlite-vec）。

两者通过 HTTP + SSE 通信，前端类型由 Core 的 OpenAPI 生成。

## 本地开发

Core Service：

```bash
cd core
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
pytest
```

桌面应用（需要 Node 22、Rust stable、uv）：

```powershell
pwsh scripts/build_sidecar.ps1    # 在仓库根目录：PyInstaller onedir 打包 sidecar
cd apps/desktop
npm install
npm run tauri dev                 # 完整桌面应用
npm test                          # Vitest
npm run gen:api                   # Core API 变化后重新生成类型
```

只调界面时可以单独启动 Core 并用浏览器打开 Vite，见 [apps/desktop/README.md](https://github.com/cristimezzz/FreeRead/blob/main/apps/desktop/README.md)。

## 设计文档

都在仓库的 [docs/](https://github.com/cristimezzz/FreeRead/tree/main/docs)：

- [PRD](https://github.com/cristimezzz/FreeRead/blob/main/docs/00-PRD.md)、[架构](https://github.com/cristimezzz/FreeRead/blob/main/docs/01-architecture.md)、[Document IR 规范](https://github.com/cristimezzz/FreeRead/blob/main/docs/02-document-ir.md)、[数据模型](https://github.com/cristimezzz/FreeRead/blob/main/docs/03-data-model.md)、[路线图](https://github.com/cristimezzz/FreeRead/blob/main/docs/04-roadmap.md)
- [ADR](https://github.com/cristimezzz/FreeRead/tree/main/docs/adr)：影响多个模块或难以回退的决策
- 里程碑记录：[M0](https://github.com/cristimezzz/FreeRead/blob/main/docs/m0/README.md)、[M1](https://github.com/cristimezzz/FreeRead/blob/main/docs/m1/README.md)、[M2](https://github.com/cristimezzz/FreeRead/blob/main/docs/m2/README.md)、M3（[知识图谱](https://github.com/cristimezzz/FreeRead/blob/main/docs/m3/kg.md)、[问答树](https://github.com/cristimezzz/FreeRead/blob/main/docs/m3/qa-tree.md)）

约定：文档用中文，代码标识符用英文；IR 和数据模型变更要同步更新文档并提升版本号；重要决策新增 ADR。

## CI 与发布

- `ci.yml`：Core（Ruff、pytest、IR / OpenAPI schema 一致性）、前端（tsc、vite build、Vitest、API 类型一致性）、Rust（fmt、clippy）。
- `desktop-build.yml`：打包 sidecar + NSIS 安装包 + 便携版 zip，在干净的 runner 上安装 / 解压后复测启动时间与退出残留（`scripts/verify_installed.ps1`）。
- 发布：更新 `apps/desktop/package.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、`core/pyproject.toml`、`core/freeread/__init__.py` 的版本号，写好 `docs/releases/<版本>.md`，合并后推送 `v<版本>` tag。工作流用完整 release 设置构建、复测，并创建草稿 Release，检查后再手动发布。

## 许可证

AGPL-3.0-or-later。欢迎提 Issue 和 PR。
