# FreeRead 仓库指南

@AGENTS.md

FreeRead 是本地优先的学术文献阅读工具，支持 Zotero / PDF 导入、重排阅读、混合检索、翻译、总结、单篇问答树、知识图谱和批注。`apps/desktop/` 是 Tauri 2 + React / TypeScript 桌面应用，`core/` 是 FastAPI sidecar，二者通过 HTTP 和 SSE 通信。`docs/` 保存设计、ADR、评测和发布记录，`wiki/` 是用户手册，`scripts/` 负责打包、评测和契约生成，`site/` 是项目主页。

先按任务查阅[开发文档索引](docs/README.md)、[桌面开发说明](apps/desktop/README.md)或[用户手册](wiki/index.md)。完整的仓库规范、验证命令和发布流程见 [AGENTS.md](AGENTS.md)。

## 必须遵守的规则

- 所有新建 Git 分支都必须符合 [Conventional Branch](https://conventionalbranch.org/)，包括 Claude Code 和自动化创建的分支。工作分支使用 `<type>/<description>`，例如 `feat/add-reader-shortcuts` 或 `claude/update-repository-guide`。允许的类型和主干分支名称见 [Git 分支命名](AGENTS.md#git-分支命名)。
- 文档用中文，代码标识符、表名和字段名用英文。跨模块或难以回退的决策必须新增 ADR。变更 IR 或数据模型时，同步更新文档并提升版本号；SQLite 结构变更通过 Alembic 迁移。
- 保持 Document IR 的坐标、占位符和引用契约。保留 Zotero 只读、sidecar 会话鉴权、系统钥匙串和外发文档内容的用户确认。长任务走持久化队列，模型调用走 `LLMGateway`，修改提示词时提升其版本。
- 变更 Core API 契约后重新生成 OpenAPI 和前端类型。按改动范围运行 [CI 对应的检查](AGENTS.md#验证与发布)，按仓库发布流程准备版本、发布说明和 tag。
