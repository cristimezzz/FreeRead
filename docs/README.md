# FreeRead 开发文档索引

| 文档 | 说明 | 状态 |
|---|---|---|
| [00-PRD.md](00-PRD.md) | 产品需求：目标用户、场景、功能清单与优先级 | 草案 |
| [01-architecture.md](01-architecture.md) | 系统架构：分层、模块、关键流程、技术选型 | 草案 |
| [02-document-ir.md](02-document-ir.md) | 统一文档模型（Document IR）规范 | 已定稿（0.1.0） |
| [03-data-model.md](03-data-model.md) | SQLite 数据模型与存储布局 | 草案 |
| [04-roadmap.md](04-roadmap.md) | 里程碑与验收标准 | 草案 |
| [m0/](m0/README.md) | M0 技术验证：解析评测、Zotero 本地 API、Tauri sidecar | 已完成 |
| [adr/](adr/) | 架构决策记录（ADR） | 持续更新 |

## 约定

- 文档使用中文，代码标识符、表名、字段名使用英文。
- 任何影响多个模块、或难以回退的决策，都要新增一份 ADR（模板见 [adr/0000-template.md](adr/0000-template.md)）。
- IR 和数据模型的变更必须同步更新对应文档，并提升版本号。
- 状态取值：`草案` → `评审中` → `已定稿` → `已废弃`。
