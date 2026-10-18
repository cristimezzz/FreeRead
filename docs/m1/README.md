# M1-P7：onedir 打包复测与 M1 验收

- 日期：2026-10-18
- 关联：[M0 sidecar 验证](../m0-tauri-sidecar.md)、[路线图 M1](../04-roadmap.md)、[ADR-0001](../adr/0001-tauri-python-sidecar.md)

## 结论速览

| 项目 | 结果 |
|---|---|
| sidecar 改为 PyInstaller onedir，经 `bundle.resources` 安装 | ✅ |
| 打包后迁移、提示词、快速解析 | ✅（发现并修复：漏带 PyMuPDF 包元数据，打包版快速解析全部失败） |
| NSIS 安装包 | 36.01 MiB（M0 onefile 时 17.56 MiB） |
| sidecar 启动到 `/health`（本机，含空库迁移） | 冷 1555 ms / 热 1537 ms（中位数） |
| 干净机器（GitHub `windows-latest`）安装 + 退出残留 | ✅ 安装 5.6 s；壳启动到 `/health` 中位数 1485 ms；关闭 / 强杀后 5/5 无残留 |
| 本机安装版（经资源管理器安装、启动） | ✅ 安装、启动、迁移、文件对话框导入、阅读器、翻译均正常 |
| M1 验收（浏览器模式 + 打包版 sidecar + 本机 Zotero + mock LLM） | ✅ 同步到看到逐段译文 39 s；离线可读 |
| 文件对话框、钥匙串、安装版重启后密钥仍在 | ✅ 本机安装版实测，见「安装版交互检查」 |

## 打包形态

```
<安装目录>/                       %LOCALAPPDATA%\FreeRead（NSIS currentUser）
├─ freeread-desktop.exe           Tauri 壳
└─ freeread-core/                 bundle.resources ← src-tauri/binaries/freeread-core/
   ├─ freeread-core.exe           PyInstaller onedir 引导 exe（即 Python 进程本身）
   └─ _internal/
      ├─ freeread/infra/db/migrations/   Alembic 迁移脚本（--add-data，按文件路径加载）
      ├─ prompts/translate.yaml          core/prompts（--add-data，运行时读 sys._MEIPASS/prompts）
      └─ pymupdf-*.dist-info/            --copy-metadata pymupdf（快速解析器取版本号）
```

- `externalBin` 只能带单个可执行文件，带不了 `_internal/`，所以整个 onedir 目录走 `bundle.resources`（`"binaries/freeread-core/": "freeread-core/"`）。`spawn_core` 用 `app.shell().command(<resource_dir>/freeread-core/freeread-core.exe)` 启动；Job Object、`--port/--token/--parent-pid`、`FREEREAD_SECRETS` 注入都不变。
- onedir 下 `freeread-core.exe` 就是 Python 进程，不再有 onefile 的"引导进程 → 子进程"两层；Job Object 仍保留，用来兜住 sidecar 自己派生的子进程（MinerU worker）。
- `tauri dev` 时 resource_dir 是 `target/debug`，tauri-build 会把 `binaries/freeread-core/` 复制过去，所以开发前同样要先跑 `scripts/build_sidecar.ps1`。
- 提示词目录找不到时 `PromptRegistry` 直接报错，sidecar 启动即失败，不会等到翻译时才报 unknown prompt。
- MinerU 等重型引擎在 M1 仍只在开发环境可用（`REPO_ROOT/.engines/`），打包版里自动判定为不可用，只用 PyMuPDF 快速模式。

### 打包后发现的问题

| 问题 | 现象 | 修复 |
|---|---|---|
| PyMuPDF 包元数据没打进去 | 打包版每个解析任务都失败：`PackageNotFoundError: No package metadata was found for pymupdf`（`pymupdf_fast.py` 用 `importlib.metadata.version` 取版本号）。单测和开发环境都覆盖不到 | `--copy-metadata pymupdf`；`scripts/measure_sidecar.ps1` 每次启动后导入一个最小 PDF 并等解析完成，CI 上的安装复测会跑到 |

## 脚本

- `scripts/build_sidecar.ps1`：onedir 打包，检查迁移脚本 / 提示词在产物里，复制到 `src-tauri/binaries/freeread-core/`。
- `scripts/measure_sidecar.ps1`：冒烟 + 启动时间。每次新数据目录（每次都跑迁移），计时到 `/health` 200，然后检查数据库已创建、日志有迁移记录、`/llm/providers` 可用、导入并解析一个 PDF。`-Mode cold` 每次把 onedir 复制到新目录。方法与 M0 相同，M0 时没有脚本化。
- `scripts/verify_installed.ps1`：静默安装 → 体积 → sidecar 冷 / 热启动 → 壳启动到 `/health`（从 sidecar 命令行取端口和 token）→ 正常关闭 / `taskkill /F` 壳各 5 次检查 `freeread-core` 残留。`.github/workflows/desktop-build.yml` 在打包相关文件变更的 PR 上运行它，结果写进 job summary。

## 数据

### 体积

| 产物 | M1（onedir） | M0（onefile，只有 `/health`） |
|---|---|---|
| sidecar | `freeread-core/` 81.3 MB，136 个文件（未压缩） | 15.9 MB 单文件 |
| 壳 `freeread-desktop.exe` | 7.4 MB | 5.7 MB |
| **NSIS 安装包** | **36.01 MiB**（37,761,528 字节） | 17.56 MiB |
| 安装后目录 / 静默安装耗时（CI） | 85.7 MB / 5.6 s | 21.7 MB / 约 7.2 s |

体积增长主要来自 core 依赖：PyMuPDF（约 40 MB 未压缩）、SQLAlchemy / Alembic、Jinja2、httpx 等。onedir 本身不比 onefile 大（同样的内容，onefile 只是压缩打包），安装包里 NSIS 会再压缩一次。

### sidecar 启动到 `/health` 可用（ms，本机，各 5 次）

每次都是新的空数据目录，所以包含建库和 Alembic 迁移；M0 的 sidecar 只有 `/health`，没有数据库。

| 模式 | 1 | 2 | 3 | 4 | 5 | 中位数 | M0 中位数 |
|---|---|---|---|---|---|---|---|
| onedir 冷 | 1573 | 1563 | 1551 | 1555 | 1549 | **1555** | 9511 |
| onedir 热 | 1537 | 1528 | 1555 | 1543 | 1522 | **1537** | 1041 |

- 热启动比 M0 慢约 0.5 s：core 现在要 import SQLAlchemy / Alembic / PyMuPDF 并跑迁移。同一天较早一次测量（加 PyMuPDF 元数据前）有 1033–1552 ms 的分布，中位数 1035 ms；差别像是 0.5 s 一档的离散跳变，原因未查，量级上都在 1–1.6 s。
- 本机冷启动和热启动几乎一样，不像 M0 那样有 7–13 s 的首次扫描开销。复制目录在仓库下的 `build/`（测量进程写不了仓库外的目录，见下文「本机受限环境」），扫描策略可能不同，不能直接当作"安装后首次启动"的结论；干净机器的数据见下文。
- 比 onefile 热启动（M0 3061 ms）快约 1.5 s，符合 M0 选 onedir 的预期。

### CI 干净机器（GitHub Actions `windows-latest`，无第三方杀毒）

由 `desktop-build.yml` 的 `scripts/verify_installed.ps1` 测得（[run 39113570107](https://github.com/cristimezzz/FreeRead/actions/runs/39113570107)，PR #9）。CI 上的安装包由 CI 自己构建，与本机构建差 0.08 MiB。

| 项目 | 结果 |
|---|---|
| 静默安装 `/S` 到 `%LOCALAPPDATA%\FreeRead` | ✅ 5.6 s；安装后 85.7 MB，141 个文件（sidecar 78.3 MB，壳 7.4 MB） |
| 安装目录里有迁移脚本、提示词 | ✅ |
| sidecar 冷启动（每次复制到新目录） | 1670 / 1602 / 1604 / 1584 / 8540 ms，中位数 **1604 ms** |
| sidecar 热启动 | 1038 / 1034 / 1528 / 1524 / 1524 ms，中位数 **1524 ms** |
| 每次启动后导入并快速解析一个 PDF | ✅（冷热共 10 次 + 预热 1 次） |
| 壳启动到 sidecar `/health` 可用（10 次） | 首次 3948 ms，之后 1468–1996 ms，中位数 **1485 ms** |
| 数据库 `%APPDATA%\FreeRead\freeread.db` | ✅ 已创建（迁移已执行） |
| 正常关闭窗口后 `freeread-core` 残留 | ✅ 5/5 次为 0，117–222 ms 内清理完（M0：90–153 ms） |
| `taskkill /F` 壳后 `freeread-core` 残留 | ✅ 5/5 次为 0，91–116 ms 内清理完（M0：326–377 ms） |

- 干净机器上也出现约 1.03 s / 1.52 s 两档的启动时间，和本机一样，说明是 sidecar 自身的行为（像是某处 0.5 s 的轮询或等待），不是杀毒软件造成的；值得在 M2 查一下。
- 冷启动 5 次里有一次 8.5 s（Defender 首次扫描新文件的典型开销），其余和热启动接近。
- 强杀壳后清理比 M0 快（onedir 只有一个进程，Job Object 关闭即结束；M0 的 onefile 有引导进程和 Python 子进程两层）。
- CI 只能检查到 `/health` 可用，没有操作界面（文件对话框、钥匙串、阅读器）。

## 安装版交互检查（本机，2026-10-18）

用本机构建的安装包（36.03 MiB，含 PyMuPDF 元数据修复）在资源管理器里双击安装（向导，默认目录 `%LOCALAPPDATA%\FreeRead`），然后从资源管理器启动。provider 指向本机 OpenAI 兼容 mock，API Key 为测试值。

| 检查 | 结果 |
|---|---|
| 安装向导 → 默认目录安装 → 勾选"运行 FreeRead" | ✅ 需要空间 88.7 MB；壳从 `\\?\C:\Users\…\FreeRead\freeread-core\freeread-core.exe` 启动 sidecar（`--port/--token/--parent-pid`） |
| 迁移 | ✅ `%APPDATA%\FreeRead\freeread.db` 已创建，文献库页正常 |
| "导入 PDF" → 系统文件对话框（PDF 过滤）→ 选评测集里一篇 | ✅ 条目出现，状态"可阅读"；打开后原版 + 重排并排显示（126 块） |
| 未配置翻译模型时打开论文 | ✅ 只弹一条提示"无法翻译：no model configured…"，没有弹窗风暴 |
| 设置 → 添加服务 → 填 Base URL 和 API Key → 保存 Key | ✅ 提示"API Key 已保存到系统钥匙串"；凭据管理器里出现 `LegacyGeneric:target=llm-keys.FreeRead`（用户 `llm-keys`）；"测试连接"正常 |
| 关闭窗口后进程 | ✅ `freeread-desktop` / `freeread-core` 都已退出 |
| 强杀壳（`Stop-Process -Force`） | ✅ `freeread-core` 随之退出 |
| 重新启动后 | ✅ 文献库、设置都在；API Key 字段显示"已保存，输入新值可替换"——这个状态来自 sidecar 内存里的密钥（`/llm/providers` 的 `has_key`），说明密钥按 钥匙串 → `FREEREAD_SECRETS` → sidecar 的路径注入成功 |
| 重启后翻译 | ✅ 首次翻译弹出同意框，同意后逐段出现译文 |

## 本机受限环境（更正：不是 Kaspersky）

第一轮本机测试时，所有新编出的无签名 exe 都写不了 `%APPDATA%` / `%LOCALAPPDATA%` / `%TEMP%`：NSIS `/S` 退出码 0 但什么都没装，壳报 `WebView2 error 0x800700AA`，sidecar 建 `%APPDATA%\FreeRead` 时 `PermissionError: [WinError 5]`。当时归因于 Kaspersky 主动防御（和 M0 的现象一致），**这个归因是错的**：

- 卸载 Kaspersky 并重启后，现象完全不变（Kaspersky 的驱动、服务都已不在）。
- 受限的只是由 Claude Code 代理会话（`claude.exe`）派生的进程：同一个 `python.exe` 能写仓库目录，写不了仓库外任何目录，进程完整性级别是普通的 Medium；而经资源管理器安装、启动的同一个安装包和 `freeread-desktop.exe` 一切正常。由代理会话直接启动的 `freeread-desktop.exe` 又会复现黑窗口。
- 所以这是开发环境（代理会话的进程沙箱）的限制，不是 FreeRead 或打包的问题。M0 记录的 Kaspersky 现象可能部分也是同一原因，没有复查。
- CI 干净机器和本机资源管理器两条路径都验证了安装版正常。代码签名仍然是发布前要做的（ADR-0001），但"未签名就会被 Kaspersky 拦成安装失败"这个结论在本机不再成立。
- 本机还装有火绒安全软件，这次测试没有观察到它拦截。

## M1 验收

路线图验收标准："从 Zotero 导入一个分类，打开任意一篇论文，3 分钟内可阅读重排版并看到逐段译文；断网后已翻译内容仍可阅读。"

第一轮验收（当时本机安装版起不来，见上文）在"浏览器模式"下做：打包版 sidecar（`binaries/freeread-core/freeread-core.exe --data-dir build/accept-data`）+ Vite 开发服务器（同源代理到 sidecar）+ 本机 Zotero 7 + 本机 OpenAI 兼容 mock（流式返回 `【译】<原文>`）。没有真实 LLM key，所以译文质量和真实 provider 的延迟不在这次验收范围内。

| 检查 | 结果 |
|---|---|
| Zotero 7 运行，从 Zotero 同步 | ✅ 6 个分类、52 个条目；快速解析任务进度在底栏可见（71 个解析任务全部完成，约 1.5 分钟） |
| 打开任一论文（AlphaFold, Nature 2021）→ 重排视图可读 | ✅ 从点击"同步"计时 **29 s 内**出现重排视图（306 块） |
| 逐段流式译文 | ✅ 首次翻译弹出"发送文档内容"同意框，同意后可视区域段落逐段出现译文；从点击"同步"计时 **39 s**（含手动点同意） |
| 显示模式切换（原文 / 对照 / 交替 / 仅译文） | ✅ 交替、仅译文已切换查看 |
| 离线：停掉 provider，重启 sidecar 后重新打开 | ✅ 已翻译段落照常显示；未翻译段显示原文，没有错误弹窗，控制台无错误 |
| 重排 ⇄ 原版双向定位与高亮 | ➖ 本次没有复查（P6 已验证，P7 未改前端） |
| MinerU 升级后自动刷新 | ➖ 未验证：打包版不含 MinerU；开发环境链路见 P3 |
| 文件对话框导入 PDF | ✅ 安装版实测（见「安装版交互检查」） |
| 设置里保存 API Key 到凭据管理器，重启后仍在 | ✅ 安装版实测（见「安装版交互检查」） |
| 关闭 / 强杀后无残留 | ✅ CI 干净机器上各 5/5；本机安装版各 1 次 |
| Playwright e2e（fake provider） | 见 P6（CI） |

## 遗留

- [x] 本机安装版：文件对话框、钥匙串保存与重启后读取（见「安装版交互检查」）。
- [ ] 代码签名（壳、sidecar 目录内 exe、安装包）。
- [ ] 用真实 provider 复测"3 分钟内看到译文"（本次用 mock）。
- [ ] 打包版的 MinerU：首次使用时下载独立环境（M2）。
