# FreeRead 仓库指南

## 项目概览

FreeRead 是本地优先的学术文献阅读工具。它从 Zotero 7 或本地 PDF 导入文献，提供原版与重排阅读、混合检索、翻译、总结、单篇问答树、知识图谱、批注和 Markdown 导出。跨文献问答与文献引用图仍在[路线图](docs/04-roadmap.md)中。

- `apps/desktop/` 是 Tauri 2 桌面壳和 React / TypeScript 前端。`src-tauri/` 管理窗口、系统钥匙串和 Core 进程；`src/app/` 管理应用状态与主题；`src/api/` 封装 HTTP、SSE 与 API 类型；`src/features/` 存放各功能。运行方式见[桌面开发说明](apps/desktop/README.md)。
- `core/` 是 Python 3.11+ / FastAPI sidecar。`core/freeread/` 由 `api/` 路由、`services/` 应用服务、`domain/` 领域逻辑和 `infra/` 适配器组成，使用 SQLite、FTS5 和 sqlite-vec。`core/prompts/` 存放版本化提示词，`core/tests/` 存放测试和评测资源。
- `scripts/` 存放 sidecar 打包、评测、生成契约和冒烟测试脚本。`site/` 是静态项目主页，`wiki/` 是 VitePress 用户文档，`.github/workflows/` 定义 CI、桌面打包和站点部署。

## 文档入口

- [README](README.md) 介绍功能、支持平台和快速上手。[开发文档索引](docs/README.md) 收录 [PRD](docs/00-PRD.md)、[架构](docs/01-architecture.md)、[Document IR](docs/02-document-ir.md)、[数据模型](docs/03-data-model.md)和[路线图](docs/04-roadmap.md)。
- [ADR](docs/adr/) 记录技术决策；后续 ADR 的修订与取代关系优先于早期设计。`docs/m0/` 至 `docs/m3/` 记录里程碑实现、评测和已知限制；以当前实现和 CI 配置核对历史记录中的命令和行为。
- [用户手册](wiki/index.md)覆盖安装、导入、阅读、AI 功能和隐私；[开发者指南](wiki/developer.md)记录 CI 和发布流程；`docs/releases/` 中的版本说明也用作 GitHub Release 正文。

## Git 分支命名

所有新建 Git 分支都必须符合 [Conventional Branch](https://conventionalbranch.org/) 规范，包括人工、代理和自动化创建的分支。

- 工作分支使用 `<type>/<description>`，并按改动用途选择前缀。仅允许 `feature/`、`feat/`、`bugfix/`、`fix/`、`hotfix/`、`release/` 和 `chore/`。
- 禁止使用任何标识 AI 代理的分支前缀，包括 `ai/`、`claude/`、`codex/`、`copilot/` 和 `cursor/`。
- 描述使用小写 ASCII 字母和数字，以单个连字符分词。点可分隔字母数字片段，例如版本号。分隔符须位于字母数字之间。
- 主干分支 `main`、`master` 和 `develop` 使用无前缀名称。

示例包括 `feat/add-reader-shortcuts`、`fix/restore-scroll-position` 和 `release/v1.2.0`。

## 必须遵守的项目规范

- **文档与决策**。文档用中文，代码标识符、表名和字段名用英文。影响多个模块或难以回退的决策必须按 [ADR 模板](docs/adr/0000-template.md)新增记录。文档状态依次为 `草案`、`评审中`、`已定稿`、`已废弃`。
- **文档解析与引用**。解析引擎通过统一接口接入，由 Normalizer 生成并校验 Document IR，阅读与 AI 功能以 IR 为共同契约。保持页码从 0 开始、左上为原点的 PDF 点坐标以及翻译占位符。总结、问答和图谱的出处必须可校验并定位到原文块。重新解析须迁移可匹配的块引用与批注，并按各功能既有规则处理无法匹配的内容。[IR 规范](docs/02-document-ir.md) · [批注迁移](docs/m2/annotations.md)
- **存储与兼容**。SQLite 结构变更必须通过 `core/freeread/infra/db/migrations/versions/` 中的 Alembic 迁移，并保留已有数据。IR 或数据模型有变更时，必须同步更新相应规范文档并提升版本号。IR 结构变更还须按兼容性调整 `schema_version`，并更新随库提交的 IR JSON Schema 及对应 CI 校验路径。[IR 版本策略](docs/02-document-ir.md#9-版本策略) · [数据迁移](docs/03-data-model.md#9-迁移策略)
- **任务与模型**。解析、嵌入、图谱抽取和批量翻译等长任务走持久化任务队列，通过 SSE 推送进度。模型调用通过 `LLMGateway` 按任务路由并复用缓存、限流和用量记录。修改提示词时必须提升其模板版本，以使旧缓存失效。[架构](docs/01-architecture.md) · [LLM 网关 ADR](docs/adr/0005-llm-gateway.md)
- **本地优先与隐私**。桌面 sidecar 仅监听 `127.0.0.1`，使用会话 token。Zotero 原库只读。API Key 存系统钥匙串，通过桌面壳注入 Core，密钥和文档全文不得写入日志。向外部模型服务首次发送文档内容前征得同意；向公网解析服务上传 PDF 前必须确认对应 Base URL，地址变更后重新确认。渲染引擎或模型产生的内容时保留现有净化和转义。[隐私说明](wiki/privacy.md) · [远程解析 ADR](docs/adr/0008-remote-parsers.md)
- **前端与 API 契约**。复用 `src/components/ui/` 的 shadcn/ui（Radix + Tailwind）、现有 AI 组件与主题令牌。阅读排版放在 `reader.css`，原生风格覆盖放在 `native.css`。Core API 契约变更须重新生成 `docs/schemas/openapi.json` 和 `apps/desktop/src/api/schema.d.ts`。[UI ADR](docs/adr/0009-shadcn-ui.md) · [AI 组件 ADR](docs/adr/0010-ai-elements.md) · [原生风格 ADR](docs/adr/0011-native-style.md)

## 验证与发布

- **Core**。在 `core/` 安装 `python -m pip install -e ".[dev,eval]"`，运行 `ruff check freeread tests ../scripts`、`ruff format --check freeread tests ../scripts` 和 `pytest`。IR JSON Schema 由 `Document.model_json_schema()` 生成，当前检查目标为 `docs/schemas/ir-0.1.0.json`。
- **API 和桌面前端**。在仓库根目录用已安装 Core 的 Python 运行 `python scripts/export_openapi.py > docs/schemas/openapi.json`，再到 `apps/desktop/` 运行 `npm run gen:api`。在该目录用 `npm ci` 安装依赖，以 `npm run build` 和 `npm test` 验证前端。桌面 `package-lock.json` 的 HTTP(S) 下载地址必须使用 `registry.npmjs.org`。
- **Rust 壳**。在 `apps/desktop/src-tauri/` 运行 `cargo fmt --check` 和 `cargo clippy --locked --all-targets -- -D warnings`。Clippy 需要已构建的前端和 sidecar 资源，CI 的准备步骤见 [ci.yml](.github/workflows/ci.yml)。
- **发布**。同步桌面 npm、Tauri、Cargo 和 Core 版本及对应锁文件，重新生成 API 契约并写 `docs/releases/<版本>.md`。发布 PR 通过 CI 并合并后，对 `main` 上的发布提交打 `v<版本>` tag。Windows、Linux、macOS 构建与冒烟测试通过后，工作流生成草稿 Release；检查正文与六个安装包后再手动发布。[开发者指南](wiki/developer.md#ci-与发布) · [桌面打包工作流](.github/workflows/desktop-build.yml)
- **许可与分发**。项目采用 [AGPL-3.0-or-later](LICENSE)。可选本机解析引擎 MinerU 和 Docling 由用户安装到独立环境，不随安装包分发。[解析引擎 ADR](docs/adr/0003-pluggable-parser.md)
