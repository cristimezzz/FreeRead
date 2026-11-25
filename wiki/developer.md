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

```bash
pwsh scripts/build_sidecar.ps1    # Windows，在仓库根目录：PyInstaller onedir 打包 sidecar
scripts/build_sidecar.sh          # Linux / macOS
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
- `desktop-build.yml` 打包 Windows 安装包和便携版、Linux AppImage／deb／rpm、macOS arm64 dmg，并在各平台运行安装和启动冒烟测试。
- 发布时同步更新桌面应用的 npm、Tauri 和 Cargo 版本（含 `package-lock.json` 和 `Cargo.lock`），以及 `core/pyproject.toml` 和 `core/freeread/__init__.py`。从仓库根目录运行 `python scripts/export_openapi.py > docs/schemas/openapi.json`，再在 `apps/desktop` 运行 `npm run gen:api` 检查生成的类型。
- 将发布说明写入 `docs/releases/<版本>.md`。发布 PR 通过 CI 并合并后，给 `main` 上包含发布提交的版本打 `v<版本>` tag 并推送。三平台构建和冒烟测试通过后，工作流会用该文件创建草稿 Release。检查正文和六个安装包后再手动发布。

## 许可证

AGPL-3.0-or-later。欢迎提 Issue 和 PR。
