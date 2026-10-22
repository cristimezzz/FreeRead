# FreeRead

本地优先的学术文献阅读工具：从 Zotero 导入文献库，把 PDF 自动重排为易读版式，并提供大语言模型翻译、AI 总结、问答树、知识图谱和批注。

项目主页：<https://freeread.work>

> 当前版本 **0.2.1**（新增 Linux 版）：M1（导入、重排、翻译）、M2（总结、问答、批注）已完成，M3 完成了单篇知识图谱与问答树，下一步是跨文献问答与文献引用图。见 [路线图](docs/04-roadmap.md)。

## 功能

- **文献库**：从 Zotero 7 导入分类和条目（本地 API，Zotero 没运行时读数据库快照），增量同步；也可以直接导入 PDF；支持批量选中、复制引用与移除。
- **阅读器**：原版 / 并排 / 重排三种视图，重排与原版双向定位；公式、表格、图片按原样渲染；文内关键词 + 语义混合检索。
- **解析引擎**：内置 PyMuPDF 快速模式；可一键安装 MinerU / Docling 到本机，或连接 mineru.net、mineru-api、docling-serve 远程服务。
- **翻译**：块级翻译，可视区域优先；对照 / 交替 / 仅译文显示；整篇后台翻译，离线可读；术语表自动抽取、可编辑。
- **AI 总结与问答**：分层结构化总结；单篇问答是一棵问答树，可追问、重答、另起、选中回答文字就此追问；引用都经过校验，可跳转到原文。
- **知识图谱**：每篇论文抽取核心实体与关系，每条关系都带原文出处；3D 链接云图浏览，点节点或关系跳回原文。
- **批注**：高亮与批注，连同总结、正文和译文导出为 Markdown。
- **大模型服务**：OpenAI 兼容接口、Anthropic 兼容端点、本地 Ollama；按任务分别选择服务和模型。
- **隐私**：数据保存在本机 SQLite，API Key 存系统钥匙串，向服务发送文档内容前征得同意。
- **更新**：设置 › 关于 里检查 GitHub Release 上的新版本，下载后按 sha256 校验；安装版自动安装并重启。

## 下载

在 [Releases](https://github.com/cristimezzz/FreeRead/releases) 下载：

- **Windows 10/11 x64**：安装包（`*-setup.exe`）或便携版（`*-portable.zip`）。程序暂未签名，SmartScreen 提示时选"更多信息 → 仍要运行"。
- **Linux x86_64**（0.2.1 起）：任意发行版可用免安装的 `*_amd64.AppImage`；Debian / Ubuntu 用 `*_amd64.deb`，Fedora / openSUSE 用 `*.x86_64.rpm`，Arch 从 AUR 安装 `freeread-bin`。需要 glibc 2.35 以上（Ubuntu 22.04、Debian 12、Fedora 36 及更新）。详见[安装说明](https://docs.freeread.work/install)。

## 快速上手

1. 第一次打开时，欢迎向导会引导你配置大模型服务、解析服务，并询问是否从 Zotero 导入；每一步都可跳过，之后在设置里改。
2. 打开 Zotero 7（可选），在 FreeRead 文献库里点"从 Zotero 同步"，或用"导入 PDF"添加文件。
3. 打开一篇文献，等快速解析完成后切到"重排"或"并排"视图。
4. 在 设置 › 大模型服务 里添加服务并保存 API Key（向导里配过就不用了），然后就能翻译、总结、问答和抽取图谱。

完整的使用说明见 [docs.freeread.work](https://docs.freeread.work)。

## 仓库结构

```
FreeRead/
├─ apps/desktop/     Tauri 2 壳 + React 前端（见 apps/desktop/README.md）
├─ core/             Python 核心服务（FastAPI sidecar）
│  ├─ freeread/
│  │  ├─ api/        路由与 DTO
│  │  ├─ services/   应用服务
│  │  ├─ domain/     ir / qa / summary / translate 领域模型
│  │  └─ infra/      zotero / parsers / llm / embedding / search / jobs / db 适配器
│  ├─ prompts/       带版本号的提示词模板
│  └─ tests/         单元测试、评测集清单、golden 标注
├─ docs/             PRD、架构、IR 规范、数据模型、路线图、ADR、各里程碑记录
├─ scripts/          打包、复测、评测脚本
└─ site/             项目主页（GitHub Pages，见 .github/workflows/pages.yml）
```

## 开发

Core Service：

```bash
cd core
python -m venv .venv
.venv/Scripts/activate        # macOS / Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
freeread-core --port 8765
```

桌面应用（需要 Node 22、Rust stable、uv）：

```powershell
pwsh scripts/build_sidecar.ps1    # 打包 sidecar 到 src-tauri/binaries/
cd apps/desktop
npm install
npm run tauri dev
```

只调界面、浏览器模式、生成 API 类型等见 [apps/desktop/README.md](apps/desktop/README.md)；开发文档索引见 [docs/](docs/README.md)。解析引擎评测（M0）的复现步骤见 [docs/m0/parser-eval.md](docs/m0/parser-eval.md#复现)。

发布：更新各处版本号并写好 `docs/releases/<版本>.md`，推送 `v<版本>` tag 后 [desktop-build](.github/workflows/desktop-build.yml) 工作流会构建、复测并创建草稿 Release。

## 许可证

FreeRead 以 [GNU Affero General Public License v3.0 或更高版本](LICENSE)（AGPL-3.0-or-later）发布。

可选的解析引擎（MinerU、Docling）不随安装包分发，由用户首次使用时下载到独立环境，并遵循各自的许可证：MinerU 为 Apache-2.0 加附加条款，Docling 为 MIT。详见 [ADR-0003](docs/adr/0003-pluggable-parser.md)。
