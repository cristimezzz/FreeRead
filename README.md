# FreeRead

本地优先的学术文献阅读工具：从 Zotero 导入文献库，把 PDF 自动重排为易读版式，并提供大语言模型翻译、AI 总结和图状结构问答。

> 状态：设计阶段（M0 技术验证）。详见 [docs/](docs/README.md)。

## 仓库结构

```
FreeRead/
├─ apps/desktop/     Tauri 2 + React 前端（待初始化）
├─ core/             Python 核心服务（FastAPI sidecar）
│  ├─ freeread/
│  │  ├─ api/        路由与 DTO
│  │  ├─ services/   应用服务
│  │  ├─ domain/     ir / kg / qa 领域模型
│  │  └─ infra/      zotero / parsers / llm / jobs / db 适配器
│  ├─ prompts/       带版本号的提示词模板
│  └─ tests/         单元测试、fixtures/pdfs 评测集、golden 标注
├─ docs/             PRD、架构、IR 规范、数据模型、路线图、ADR
└─ scripts/
```

## 开发（Core Service）

```bash
cd core
python -m venv .venv
.venv/Scripts/activate        # macOS / Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
freeread-core --port 8765
```
