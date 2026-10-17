# FreeRead

本地优先的学术文献阅读工具：从 Zotero 导入文献库，把 PDF 自动重排为易读版式，并提供大语言模型翻译、AI 总结和图状结构问答。

> 状态：M0 技术验证已完成（[总结](docs/m0/README.md)），下一步 M1 MVP。详见 [docs/](docs/README.md)。

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

## M0 解析评测

需要先启动 Zotero 7；模型缓存在 `.engines/cache/`，PDF 与 golden 不入库。

```bash
bash scripts/m0_setup_engines.sh                                  # MinerU / Docling 独立环境
core/.venv/Scripts/python scripts/m0_build_eval_set.py            # 从 Zotero 构建评测集
core/.venv/Scripts/python scripts/m0_run_parsers.py               # 运行引擎、生成 IR
core/.venv/Scripts/python scripts/m0_golden.py consensus          # golden 共识草稿（另有 render / merge）
core/.venv/Scripts/python scripts/m0_report.py                    # 指标 → docs/m0/
```

详见 [docs/m0/parser-eval.md](docs/m0/parser-eval.md#复现)。
