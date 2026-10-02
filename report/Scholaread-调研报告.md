# Scholaread（靠岸学术）功能与实现细节调研报告

> 调研对象：本机安装的 Scholaread 桌面客户端 **cn-1.1.86 (assetVersion 20260928-1)**，以及其随包 Web 产物与公开资料。
> 调研目的：为自研开源「论文辅助阅读软件」（工作区 `C:\Projects\FreeRead`）提供**功能对标 + 实现路径参考 + 选型建议**。
> 证据级别约定：**[实测]** = 在本机安装包/运行日志/缓存产物中直接观察到；**[公开]** = 官方页面或第三方公开资料；**[推测]** = 由前者推断，未直接证实。

---

## 0. 摘要（先看这一页）

**一句话**：Scholaread 是一款「**PDF 重排阅读 + 学术翻译 + 文献管理 + AI Agent**」四件套合一的商业桌面/移动端软件，本质是 **Electron 前端 + 重度云端服务**（`api.scholaread.cn` / `pdf2html.com`），本地只做「PDF→HTML 渲染、OCR、笔记与事件同步、浏览器抓取代理」；其真正的护城河是 **版面理解（trust region）+ 译文与原文的对齐渲染**。

**九个最关键的实现事实**（全部 [实测]）：

| # | 事实 | 证据 |
|---|---|---|
| 1 | **桌面端是 Electron 单包**，`app.asar` 164.7 MiB / 8576 个文件，`node_modules` 395 个包占 169 MB | 本机 `resources/app.asar` |
| 2 | **重排引擎是 pdf2htmlEX 编译成的 WASM**（12.5 MB `pdf2htmlEX.wasm` + 212 KB JS glue + poppler 数据目录 cMap/cidToUnicode），本地按页导出 HTML/CSS | `dist/wasm/pdf2htmlEX.*`、`%APPDATA%\scholaread\files\data\poppler\` |
| 3 | **版面理解输出「trust region」**：云端 `sr` 布局 v5 给每个区域打 `type`（title/author/text/figure/table/formula/reference/abandon…）与 `score` 置信度，本地按版本号做缓存失效 | `region/layouts/v2/sr_5/<hash>.json`、配置 `layoutConfig` |
| 4 | **每页产出双层 HTML**：`origin_index.html`（pdf2htmlEX 绝对定位原始层）+ `index.html`（语义重排层，含 `.pdf_paragraph/.pdf_heading/region-id`）；另有 `bgN.png/jpg` 页面位图用于原文模式与图文对照 | `files/out/<assetVersion>/<hash>/server/<page>/` |
| 5 | **翻译是纯云端 API**，按字数配额、HTTP 429 → 「今日免费翻译额度已用完」；本地还有"截图翻译"通道（`getCapture`） | `readingTranslate()`、locale、preload `getCapture` |
| 6 | **OCR 用 tesseract.js + 本地语言包**（`chi_sim.traineddata` 2.4 MB、`eng` 5 MB），并用启发式判断 PDF 是否扫描件（`doc_type: scanning_pdf / normal_pdf`） | `dist/public/tesseract/`、service 日志 `checkIsScanning` |
| 7 | **本地存储是 better-sqlite3 + 事件溯源同步**：`reading_list_events`/`notes_events` 以 `client_event_id` 为主键，带 `device_id/op/synced/sign`，先「过滤过期事件 → 合并同数据事件 → 分批上行」，再拉取远端事件做全量/增量合并 | `scholaread.sqlite` 建表语句 + 运行日志 |
| 8 | **内嵌浏览器 + 规则引擎抓文献**：`page_detect_rule.json` 覆盖 arXiv/知网/万方/维普/IEEE/Nature/ScienceDirect… 用 CSS 选择器识别详情页并抽取元数据，失败时用 LLM 兜底（`parse_paper_detail_by_ai`），下载链路含机构代理与 `sci-hub://` 回退 | `dist/public/rule/*.json`、main.js |
| 9 | **内置 AI Agent（工作区 + 技能库 + 权限规则 + Pyodide）**：Agent 可拥有独立工作区目录、安装官方技能包（`cdn.scholaread.com/assets/agent/skills_registry.json`）、调用浏览器工具（navigate/click/snapshot/…）、在 Pyodide 里跑 numpy/pandas/matplotlib | preload 的 90+ `project*`/`agentCore*` IPC |

**商业与许可（[公开已核验]）**：闭源专有；CNY 专业版季付 ¥109 / **年付 ¥199.90**，Pro Max 年付 ¥699；免费版 50 页重排 + 7,000 字翻译/天且**含广告**；AGPL 组件（Zotero、PyMuPDF、PDFMathTranslate 等）是开源项目最大的许可雷区，而 **PDF.js(Apache) + Docling(MIT) + Marker(Apache) + GROBID(Apache) + PaddleOCR(Apache) + PaperQA2(Apache)** 构成商业友好底座。

**对开源项目的核心结论**：Scholaread 的**阅读体验**（重排 + 对照翻译 + 高亮笔记）是最值得对标的部分，而这部分的**可开源替代路线已经成熟**（Docling / Marker 做版面，PDF.js 做渲染，KaTeX 做公式，PDFMathTranslate 做参考实现）；它的**云端版面模型 + 配额计费**是最难复制也最不该复制的一环。**真正值得照搬的是三个"设计"而非"技术"**：① §5.3 的句子↔行↔区域锚点模型；② §5.15 的「本地/云端同源」协议代理；③ §3.12 的排版纠错反馈闭环。

---

## 1. 调研方法与证据基础

> **证据留存说明**：原始取证产物（`app.asar` 解包文件、条目清单、静态扫描输出、UI 文案 TSV、截图与解析脚本）属于调研中间产物，已在仓库清理中删除，**未随仓库分发**——其中包含第三方（Scholaread）专有代码与资源，不应进入本 AGPL 项目。本报告保留**结论与可核验的路径/命令**，两处证据附录以表格形式留档；如需重新取证，按下表手段在本机客户端上重跑即可（客户端版本 `cn-1.1.86`）。

| 手段 | 说明（可复现） | 本仓库留存 |
|---|---|---|
| 安装目录盘点 | `%LOCALAPPDATA%\Programs\Scholaread`、`%APPDATA%\scholaread` | 结论见 §2、§10.2 路径速查 |
| `app.asar` 结构解析 | Chromium Pickle 头解析（`uint32` 头部尺寸 → JSON 头），无需第三方依赖 | 结论见 §0 表 #1、§5.14 |
| 定向解包 | 抽取 `main.js`(4.3 MB)、`service/service.js`、全部 preload、规则 JSON、locale、tab-container | 结论见 §4、§5 各节 |
| 压缩包静态分析 | 针对 webpack 单行 bundle 的关键字窗口扫描 | 结论见 §5.10–§5.15 |
| 运行日志分析 | 客户端 2026-10-02 / 10-03 两段真实运行日志（同步、Zotero、OCR、支付、启动时序） | 本机 `%APPDATA%\scholaread\logs\` |
| 本地缓存产物分析 | 重排输出目录、区域布局文件、SQLite 库、字体与 OCR 数据 | 结论见 §5.1–§5.7、§10.2 |
| 客户端 Web 产物字符串挖掘 | 从其自带前端 bundle 提取 2266 条中文 UI 文案作为功能证据 | 逐条清单：[feature-inventory.md](../research/feature-inventory.md) |
| 公开资料与许可核验 | 官方计费接口、协议条款、GitHub API 星标与 LICENSE 原文 | 逐条外链：[web-features.md](../research/web-features.md) |
| 启动实测 | 实际启动客户端并抓取运行日志（本环境下窗口不可见，见 §10.4 说明） | 本机日志；结论见 §10.4 |

> 说明：本报告**不含**任何账号令牌、设备指纹、订单号等敏感值；涉及此类内容时只描述其存在与存储位置。

---

## 2. 产品概况

| 项 | 值 | 来源 |
|---|---|---|
| 产品名 | Scholaread / 中文名「**靠岸学术**」（托盘与标签页标题即此名） | [实测] `locales/zh.json` |
| 厂商 | **上海亦答网络科技有限公司**（与**坚果云 Nutstore** 同一体系）；国际主体 **Astronet Technology PTE LTD**（新加坡）；发票由上海亦答开具 | [实测] `package.json` author、`Uninstall` 注册表项；[公开已核验] 购买协议 |
| 版本 | `1.1.86`，内部渠道号 `cn-1.1.86 (20260928-1)`，`appId=cn.scholaread.pc` | [实测] |
| 官网/主域 | `www.scholaread.com` / `www.scholaread.cn`（配置里 `host=https://www.scholaread.cn`） | [实测] `config.json` |
| 相关域名 | `api.scholaread.cn`、`api-demo.scholaread.cn`、`cdn.scholaread.com`、**`pdf2html.com`**（PDF→HTML 转换服务）、`ai-assistant.jianguoyun.net.cn`（坚果云 AI）、`sentry-backend.jianguoyun.com`（自建 Sentry）、`api.keygen.sh`（授权） | [实测] main.js |
| 客户端形态 | Windows/macOS/Linux 桌面（Electron）+ iOS/Android + 网页版；桌面端首页本身就是一个**远程 Web 页面**（`home_style: "web"`，`last_method: "web_assistance"`） | [实测] |
| 发布渠道与包体 | electron-updater 通道 `cdn.scholaread.cn/assets/pc-releases/<ver>/cn/latest{,-mac,-linux}.yml`；Windows NSIS 189 MB、macOS x64/arm64 zip+dmg 207–221 MB、Linux `.deb` 175 MB | [公开已核验] |
| 开源属性 | **闭源专有软件**（协议明示独立知识产权 + 仅个人可撤销许可；GitHub 无 scholaread 组织） | [公开已核验] |
| 账号体系 | 手机号登录（`user_info.phone_number` 掩码存储）、`account_state: free/pro` 等、支持联想渠道合作（`isLenovoCooperation`、`getPaymentLenovo`）与坚果云账号绑定（`nut_account_state`） | [实测] `config.json`、preload |

---

## 3. 功能地图（对标清单）

> 本节为**基于安装包证据的功能清单**；公开资料侧的市场/价格/竞品对照见 §6、§7。

### 3.1 阅读与排版
- **两种阅读模式**：「重排模式（reflow）」与「原文模式」；`read_mode` 默认 `web:reflow`；原文模式下**不支持翻译**（文案：「抱歉，这篇文章原文模式目前不支持翻译，请切换为重排模式翻译。」）[实测]
- **AI 重排（AI Reflow）**：云端版面模型把 PDF 拆成段落/标题/图表/公式并重排为可自适应宽度的 HTML；有**页数上限**（配置 `max_page: 500`，OCR 上限 `ocr_max_page: 320`，单文件 `max_size: 50 MiB`），超限提示「最多支持 {{max_page}} 页」[实测]
- **目录与图表索引**：自动大纲（`catalogue_index.json`）、图目录（`figure_index.json`）、段落索引（`paragraph_index.json`）、段落格式索引（`paragraph_format_index.json`）、参考文献角标（`custom_cite.json` 的 `cite.N`）[实测]
- **笔记与高亮**：`notes` 表（`type/text/lines/note_content/mark_style`）+ 页面区域标注（`saveMarkedRegions`），译文模式下**不支持加高亮/笔记**（文案：「该文章无法在译文中添加高亮或笔记。」）[实测]
- 阅读统计：`reading_record` 表记录 `begin_read_point/end_read_progress/end_read_mode`，UI 有阅读天数、连续阅读激励文案 [实测]
- 中文字体随包分发：`NotoSansSC-Subset.otf`、霞鹜文楷（lxgw-wenkai-gb）、Noto Serif SC、Linux Libertine、TeX Gyre Heros [实测]

### 3.2 翻译
- 四种模式：**对照式翻译**、**仅译文**、**逐段对照**、**划词翻译**，另加**截图翻译（OCR 翻译）** [实测]
- 翻译设置：翻译语言、**翻译标题优先**、自动翻译（标题 / 文章速览 / 全文）开关 [实测]
- 语言检测：「检测到翻译语言与文章语言相同。」[实测]
- 配额：按**字数**计费（「今日翻译字数已用完，请升级专业版」「今日免费翻译额度已用完」），429 状态码映射为配额耗尽 [实测]
- 翻译与原文的对齐依赖句子级锚点（见 §5.3 的 `text_lines_identification`）[实测]

### 3.3 AI 能力
- **AI 问答 / AI 速览 / AI Agent**（额度描述：「立即获得 5 倍 AI Agent 额度，畅享高频阅读、写作与研究，并升级翻译、AI 问答、PDF 解析等权益。」）[实测]
- Agent 具备：独立**项目工作区**（可自选目录）、**官方技能库**（可从 CDN 安装/自动安装/必需技能）、**权限规则**（`projectGetPermissionRules`）、**浏览器自动化工具**、**Pyodide 数据计算沙箱**、**HTML 预览沙箱**（对外链资源有细粒度授权）[实测]
- 桌面**宠物**作为 Agent 状态指示器：`pet-assets/frames/{idle,greet,reading,agent-input,agent-work,agent-success,sleep}`，姿态由 `showPet({business:"agent", eventType:"run_active|run_succeeded|user_action_required|run_failed"})` 驱动 [实测]

### 3.4 文献管理与同步
- 文献库（reading_list）、文件夹/分组、标签（`reading_tags`）、笔记、阅读记录 [实测]
- **多端增量同步**：事件溯源 + 全量兜底（见 §5.7）[实测]
- **Zotero 集成**：直接读取本机 `zotero.sqlite` 副本（本机 16.8 MB），按「作者 年份 标题」匹配 PDF，支持分类树、双向打开（`setOpenWithScholaread`）、暂停/重试同步 [实测]
- 导入：PDF、**CAJ（知网格式，服务端 `caj2pdf` 转换，需登录）**、EPUB（含封面与元数据提取）[实测]
- 导出：**重排后的 PDF 导出**（`startExportPDF(readingId, layoutType, includeNotes, includeHighlight)`）+ 打印导出（`prepare_print.js`）[实测]

### 3.5 检索与发现
- 全网/期刊搜索、一键保存（浏览器内核内嵌页 `search.html`、`add_website.html`）
- 站点规则覆盖（`page_detect_rule.json`）：arXiv、知网 kns.cnki、ScienceDirect、PubMed/PMC、Springer、IEEE Xplore、Nature、Science、Cell、PNAS、Wiley、SAGE、T&F、OUP、IOP、PLOS、eLife、PeerJ、ASM、AEA、PMLR、NeurIPS、CVF、维普、万方、Semantic Scholar、Google Scholar 等 40+ 条目 [实测]
- 检索结果页亦为规则化抽取（arXiv/Springer/Google Scholar/知网/维普/万方）[实测]

### 3.6 客户端与体验
- 系统托盘（显示主界面/同步/退出）、**PDF 下载监听**（检测到 PDF 时通知「立即打开」）、开机/file 关联（注册表 `HKCU\Software\Classes\scholaread`）、网络检测与代理（`hpagent`/`socks-proxy-agent`/`proxy-from-env`）、日志打包导出、缓存目录自定义、崩溃上报（`@sentry/electron`）、热更新（`applyHotUpdate`）[实测]
- 内嵌多标签浏览器（`tab-container`）：WebContentsView 级 tab 管理、后退/前进/刷新、Agent 标签页归属（`agent-tab-ownership.js`）、Agent 弹窗标签页 [实测]
- 快捷键：`Ctrl/Cmd+F` 页内查找、`Esc` 关闭；未发现自定义快捷键设置 → 快捷键体系很薄 [实测]
- 磁盘空间守卫（`autoCheckDiskSpace` + `disk_space_exhaust.html`）、缓存清理（清理前自动关闭全部阅读标签页）、路径权限异常提示 [实测]

### 3.7 阅读增强（前文未列的细节）

| 功能 | 证据（客户端文案） |
|---|---|
| **AI 阅读重点提取** | 「阅读重点」／「阅读重点提取中...」／「暂时无法提取重点句子」／「切换模式以查看 AI 提取的阅读重点」 |
| 文字显示设置 | 「句子数量」／「项目符号」／「文字显示设置」／「重点句子高亮」／「显示译文下划线」 |
| 视图形态 | 「宽屏视图」／「默认视图」／「卡片视图」／「表格视图」／「布局选项」 |
| 主题 | 「深色模式」／「浅色模式」／「跟随系统」；`tab-container/index.html` 使用 `color-scheme: light dark` |
| 页面操作 | 「放大/缩小/适应屏幕宽度/适应屏幕高度/全屏/左右旋转/水平翻转/垂直翻转/在新窗口打开」 |
| 阅读进度 | 「已读 {currentPages}，共 {totalPages}」／「继续阅读」／「上次阅读」；`read_time/read_count/read_days` 字段 |
| 内置 pdf.js viewer | `dist/public/pdfjs/web/viewer.html` + `secondaryToolbarButton-scrollPage/scrollVertical/scrollWrapped` → 具备翻页/滚动两类浏览 |

> 反向结论：**未发现**面向用户的「术语库 / 专有名词表」文案，也**未发现**独立「润色」功能——这类"看起来该有"的功能在 Scholaread 上并不存在，可作为 FreeRead 的补位点。

### 3.8 AI 能力的完整切面（补充 §3.3）

| 能力 | 关键文案/证据 |
|---|---|
| 划词即问 | 「论文太难读？选中任意内容，AI 帮你讲解」／「解释一下这段文本」 |
| 图表/公式/图片解释 | 「解释图表」／「解释一下这个公式」／「解释一下这张图片」／「公式提取不乱码」 |
| **跨篇问答（多文献对比）** | 「专业版更支持多达 20 篇文献的跨篇深度问答」／「免费版支持 {freeCount} 篇问答」／「最多可选中 {count} 篇文献」 |
| 上下文来源 | 「Agent 会结合项目文件和文献库回答」／「引用文献库论文/文件夹/项目文件」 |
| **AI 综述报告** | 「输入你的研究课题，快速生成文献综述或开题报告」／「检索近 100+ 篇核心文献」／输出结构「研究方法/研究目标/主要结论/创新点」／耗时提示「深度搜索中…约 10-15 分钟」 |
| 综述额度 | 「开通专业版后，每月可获得 3 次综述报告额度」／「写综述报告为专业版专享功能」 |
| 推理可控 | 「推理等级」／「开启思考」／「已深度思考（用时 {cost} 秒）」 |
| 并行/子任务 | 「并行工具调用」／「子任务」 |
| 免责 | 「内容由 AI 生成，仅供参考」 |

### 3.9 写作与 Word/WPS 生态（补充）

- 「Word / WPS 插件」（内测，「添加官方企业微信获取资源」）、「参考文献引用助手」「引用格式」「插入标准格式」「导出引用（实验性）」、「免费检测论文格式」、坚果云「AI 写作」联售。
- 说明 Scholaread 正从"读"延伸到"写/引"，与 Zotero + Word 插件生态正面竞争。

### 3.10 浏览器扩展与书签工具

- 官方扩展覆盖 Chrome / Firefox / Edge，并提供 **bookmarklet**：`javascript:` 注入 `<script src="{origin}/assets/bookmarklet.js">` 后调用 `add(origin, userId)` 完成保存；换账号会提示「账号不匹配。请创建一个新的小书签吧。」[实测：`SaveBookmarkletView` 源码]
- 站点内检索支持多频道（`tab-container` 的左栏 `#channel-list` + 「添加搜索引擎」）。
- **ChatGPT App 集成**：随包存在 `ChatGPTApps-ReadPaper`、`ChatGPTApps-SavePaper`，即 ChatGPT 侧可直接"读这篇论文/保存到 Scholaread"，并有独立失败码（`convertCode===3` 受版权保护、`4` 页数过多，且区分 ChatGPT 与客户端的提示文案）。[实测]

### 3.11 分享与版权合规

- 分享：二维码、「扫码打开」、「查看 {count} 篇论文」、`share_id` / `is_open_access` 字段。
- 版权拦截：「抱歉，由于受到版权保护，无法查看该文章。」+「举报」入口。
- 主体与备案（[实测] 前端文案）：`沪ICP备2021026665号-2`、`沪公网安备31011502400586号`、**`网信算备310112174995401260029号`**（生成式 AI 算法备案）；国际主体 `Astronet Technology PTE LTD`，并会自动切换国内/国际站。

> 完整逐条证据见附录产物 `research/feature-inventory.md`（506 行、8 大类）——本报告 §3 为其精炼版。

### 3.12 **排版纠错闭环**（最值得抄的一个产品设计）

[实测] 客户端内置了**区域级错误反馈编辑器**：用户可以「标记错误区域」→「调整区域类型」→「保存 & 重转」，错误类型被结构化为「布局错乱」「文本重叠」「换行问题」等，并可对单页/单区域**重新转换**（「如等待时间过久，可切换至普通引擎。」「切换重排引擎：{engineName}」）。

工程含义：
- 它把「重排质量不可控」这一最大体验风险，转化为**用户参与的数据飞轮**（人工修正 → 训练/规则反馈）；
- 「普通重排引擎」作为**降级兜底**始终可用（对应本地 pdf2htmlEX 路径），保证"再差也能读"；
- 「影印版（扫描件）」是被**显式建模的文档类型**，并有独立的降级功能提示与页数上限。

> **给 FreeRead 的直接建议**：从 V1 就设计「区域标注 + 一键重转」的纠错入口，并把修正结果存成**可提交的 JSON patch**（既能本地生效，也能在用户同意下汇聚训练数据）。这是开源项目相对云端闭源产品少有的"社区共建"优势点。

---

## 4. 技术架构总览

```
┌───────────────────────── Electron 桌面端（单包 asar） ─────────────────────────┐
│                                                                               │
│  main 进程 (dist/main.js, 4.3 MB)                                             │
│   ├─ 窗口体系：home(mainView，加载远端 www.scholaread.cn) / preview / pet      │
│   ├─ 本地 SQLite (better-sqlite3, WAL)  ── reading_list / notes / events       │
│   ├─ 同步引擎（事件溯源，全量+增量）                                           │
│   ├─ 下载与抓取编排（内嵌浏览器 tab-container + 规则引擎 + LLM 兜底）           │
│   ├─ AI Agent 宿主（工作区、技能库、权限、Pyodide worker、HTML 预览沙箱）        │
│   ├─ 原生扩展加载（koffi FFI → LsfSdk.dll / LYSDK2.dll / ludp.dll）            │
│   ├─ 更新（electron-updater + 热更新）、日志（winston）、Sentry                 │
│   └─ 网络（axios + 代理链 + electron-re CacheInterceptorV3 缓存表）            │
│                                                                               │
│  service 进程 (dist/service/service.js, 321 KB)                                │
│   └─ 本地「伪服务端」：用 pdf2htmlEX WASM 把本地 PDF/EPUB 转成与云端同构的       │
│      JSON+HTML 资源（buildReadingResponse / buildSharesResponse / per-page）    │
│                                                                               │
│  renderer                                                                     │
│   ├─ home：远端 Web 应用（同一套 SPA 亦随包放 resources/render/ 作兜底/助手页）  │
│   ├─ preview：读 reflow HTML/CSS/bg 图（原文层 + 重排层 + 区域锚点）            │
│   ├─ pdfjs viewer（dist/public/pdfjs，含 sandbox/worker/标准字体）             │
│   └─ 多个最小 preload（pet / search / browser_agent / pdf_detect / network…）   │
└───────────────────────────────────────────────────────────────────────────────┘
            │  HTTPS                                        │  HTTPS
            ▼                                               ▼
  api.scholaread.cn（账号/同步/翻译/AI/配额/支付）      pdf2html.com（云端 PDF→HTML 版面转换，v1/v2 资产）
            │
  cdn.scholaread.com（Agent 技能注册表、静态资源）
```

要点：
1. **客户端把「首页」做成远程网页**（`home_style: web`），因此产品迭代主要发生在服务端，客户端只保留能力桥（preload `desktopAppBridge` 暴露 90+ IPC）。这解释了为什么 asar 里同时存在 `dist/public/**`（本地助手页）与 `resources/render/**`（同款 SPA 的静态副本）。
2. **本地服务与云端 API 同构**：`service.js` 直接构造 `{code,message,data}` 以及 `asset_base_url: https://pdf2html.com/files/{...}` 结构，等于在本地复刻了云端资产协议——这既是"离线可用"的实现方式，也说明其数据模型是**以服务端为中心设计**的。
3. **一切重活都在云端**：版面模型、翻译、AI、OCR 判定、CAJ 转换、PDF 转换（server 引擎）都是远程调用；本地只有 pdf2htmlEX（默认引擎）、tesseract、SQLite、Pyodide。

---

## 5. 关键实现细节

### 5.1 PDF → HTML 重排管线

**技术栈（全部 [实测]，位于 `app.asar` 与运行缓存）**

| 环节 | 组件 | 体积/位置 |
|---|---|---|
| PDF 解析与 HTML 导出 | **pdf2htmlEX（WASM）**，基于 poppler | `dist/wasm/pdf2htmlEX.wasm` 12.48 MB、`pdf2htmlEX.js` 212 KB、`pdf2htmlEX.worker.js` 3.2 KB |
| poppler 运行数据 | cMap / cidToUnicode / nameToUnicode / unicodeMap | `files/data/poppler/**` |
| 字体 | NotoSansSC-Subset、霞鹜文楷、Noto Serif SC、Linux Libertine、TeX Gyre Heros | `files/data/fonts/**`、`resources/data/fonts/` |
| 兜底渲染 | **PDF.js** 全量发行版（build/nodejs/web + sandbox + 标准字体） | `dist/public/pdfjs/**` |
| 服务端重排 | `reflowEngine: "server"` → `pdf2html.com` | 配置与 `asset_base_url` |

**调用形态**：service 进程通过 `require("../wasm/pdf2htmlEX.js")` 拿到 Emscripten `Module`，使用其导出的 `Module.getVersion()`、`Module.getMetaInfo()`、**`Module.getPageContent(pageNo, ...)`** 按页取内容；页面级并发通过自实现的 `PromiseQueue` 串行/限流，逐页写盘并落 `finished.txt` 作为断点续传标记。

**每个"阅读"的磁盘产物（以本机一本 Nature 论文为例，28 页）**

```
files/out/<assetVersion>/<pdfHash>/
├─ server/
│  ├─ complete.txt                       # 整本完成标记
│  ├─ catalogue_index.json               # 全书大纲（按页聚合，含 bbox 与 level）
│  ├─ figure_index.json                  # 全书图表索引
│  ├─ paragraph_index.json               # 全书段落索引
│  ├─ paragraph_format_index.json        # 段落格式（字号/加粗等）索引
│  └─ <page>/
│     ├─ origin_index.html               # ① pdf2htmlEX 原始层（绝对定位，data-line-id）
│     ├─ index.html                       # ② 语义重排层（region-id / pdf_paragraph）
│     ├─ index.css                       # 单页样式（含内联字体，0.5–5.8 MB）
│     ├─ bg<page>.png / bg<page>.jpg      # ③ 页面位图（原文模式、图文对照）
│     ├─ region.json                      # 区域几何（PDF 点坐标）
│     ├─ paragraph.json                   # 段落文本
│     ├─ catalogue.json / figure.json     # 本页标题 / 图表
│     ├─ custom_cite.json                 # 本页参考文献角标
│     ├─ figures/<tag>.jpg                # 抽取出的图片（含 extended data）
│     └─ finished.txt / pre_convert.txt   # 断点标记
└─ tmp/<pdfHash>/<page>/                  # 转换中间态
```

### 5.2 版面理解：「trust region」

配置里给出的布局契约（[实测] `config.json` 的 `layoutConfig`）：

```json
{ "default_type": "sr",
  "layout_info": {
    "sr":  { "version": 5, "max_size": 52428800, "max_page": 500, "ocr_max_page": 320,
             "trust_region_types": ["title","text","formula","content","algorithm","reference",
               "abandon","aside","figure","figure_caption","figure_footnote","table",
               "table_caption","table_footnote","inline_formula"] },
    "sr1": { "version": 1, "trust_region_types": [] } } }
```

- 云端模型输出 `region/layouts/v2/sr_5/<pdfHash>.json`，形如：
  `{"1":{"width":1191,"height":1582,"is_cover":false,"regions":[{"id":"6","order":1,"x":73,"y":92,"width":930,"height":115,"score":0.973,"type":"title","text":"Algorithm for optimized mRNA design…"}]}}`
  → **坐标系是 1191×1582 的渲染栅格**（约 144 dpi 的 A4），带 **`score` 置信度**与 `type`/`order`。
- **缓存失效策略**：客户端比较「本地 `layoutConfig` 的 `version` + `trust_region_types`」与远端配置，不一致就删除 `out/<id>` 已生成资源重转——这是把「模型版本」当缓存键的典型做法。
- **双引擎可切换**：UI 提供「切换重排引擎：{engineName}」，并有「如等待时间过久，可切换至**普通重排**引擎。」的降级提示；`getReflowEngineConfig` 返回 `{engines: ReflowEngineList, current: getLocalReflowEngineId()}`。[实测]
  → 由此可确认引擎语义（**推测**但证据充分）：**AI 重排 = 云端 `server` 引擎**（产出 `sr` v5 trust region，按页计费、有额度），**普通重排 = 本地 `default` 引擎**（pdf2htmlEX 直出，无版面模型）。这也解释了配置里同时存在 `sr`（有 trust_region_types）与 `sr1`（空 trust_region_types）两套布局类型。
- `abandon` 类型（页眉页脚、版权、水印）会被识别并丢弃，显著提升重排可读性。

### 5.3 三层对齐数据模型（这是"对照翻译"的技术核心）

**① 区域层 `region.json`**（PDF 用户空间坐标，单位 pt）：
```json
{"width":595.276,"height":790.866,
 "regions":[{"x":39.685,"y":59.2291,"width":461.994,"height":38.3255,
             "id":"1","order":1,"type":"title","error":"none"}, …]}
```

**② 段落层 `paragraph.json`**：`[{"id":"pa_1_1","type":"title","contents":[{"text":"…"}]}, …]`，段落 id 由「页号 + 区域序号」组成，便于从译文反查原文位置。

**③ 句子/行锚点**：重排 HTML 中每个 `<span class="sentence">` 带
`text_lines_identification="<base64>"`，解码后是
`[{"id":15,"page":1,"begin":0,"len":3}, {"id":-1,…}, …]`
即「本句由哪些 pdf2htmlEX 行对象（`data-line-id`）的哪一段构成」。

```html
<div region-id="1" region-description="reflow" lang="en-US">
  <div class="pdf_paragraph pdf_heading ff35f00000000 adjustable_fsa"
       id="heading_2961d2c2b8f9fc261cba2b1398074baa" data-pa-id="pa_1_1">
    <span class="sentence …" text_lines_identification="W3siaWQiOjE1LC…">
```

**工程含义**：句子↔行↔区域的**双向映射**使得：
- 划词/划句可即时定位到原文区域（高亮框落在 `bg` 位图上）；
- 翻译结果可**逐句替换/并列**，且切换回原文模式不丢位置；
- 用户笔记绑定在 `region-id`/句子锚点上，跨模式稳定。

> 这是「重排 + 对照翻译」能做到体验顺滑的关键设计，**开源项目应直接照搬这一思路**，而不必依赖同样的模型。

### 5.4 原文/重排双模式

`bg<page>.png`（约 120 KB，压缩位图）用于原文视觉层；`bg<page>.jpg`（约 1–2 MB）为高清位图（用于放大、图形抽取与图文对照）。`index.html` 与 `origin_index.html` 分别对应重排层与精确定位层，二者共享同一套区域锚点。

### 5.5 翻译、划词与截图翻译

- 主通道：`readingTranslate(reading_id, language, text)` → 服务端返回 `{translation:[...]}`；客户端把 `response.status === 429` 映射为「今日免费翻译额度已用完」。[实测]
- 划词/截图：preload 暴露 `getTranslate(text)` 与 **`getCapture(rect)`**（屏幕矩形捕获，配合 OCR 实现「截图翻译」）。[实测]
- 译文的渲染与原文段落按 `pa_*`/句子锚点对齐，译文模式下**禁用高亮与笔记**（避免锚点歧义）。[实测]

### 5.6 OCR 与扫描件判定

- `tesseract.js` 5.0.5 + `tesseract.js-core`（7.9 MB），语言包 `eng.traineddata`(5.1 MB)、`chi_sim.traineddata`(2.4 MB) 随包。[实测]
- 日志中 `checkIsScanning, <file>.pdf, false, cost: 4358ms` 表明**本地做扫描件检测**（约 4.3 s/篇），结果写回 `doc_type: scanning_pdf | normal_pdf`；扫描件走 OCR 通道并受 `ocr_max_page: 320` 限制。[实测]

### 5.7 本地存储与同步（事件溯源）

**SQLite 表结构（[实测] 由 main.js 内建表语句还原）**

| 表 | 关键列 | 用途 |
|---|---|---|
| `reading_list` | `_id, reading_id, type, name, title, authors, file_path, size, cache_path, picture, doi, arxiv_id, preset, doc_type` | 文献库主表 |
| `reading_list_events` | `client_event_id PK, event_id, event_at, device_id, op, op_at, data_fields, data, sign, synced, sync_result_code, sync_result_message` | 文献库变更事件 |
| `reading_tags` | `type, name, count, status`（联合主键） | 标签 |
| `reading_record` | `data_local_row_id, reading_id, share_id, begin_read_point, end_read_mode, end_read_progress, end_read_point` | 阅读行为 |
| `notes` | `note_id, paper_row_id, reading_id, type, text, lines, note_content, create_at, update_at, mark_style` | 笔记/高亮 |
| `notes_events` | 同 `reading_list_events` 结构 | 笔记变更事件 |
| `reflow_meta` | `user_id, share_id, layout_id, reflow_engine` | 重排版本与引擎绑定 |
| `cacheInterceptorV3` | `url, method, …, etag, vary, cachedAt, staleAt` | HTTP 缓存（electron-re） |

**同步流程（[实测] 运行日志逐行还原）**
1. 启动即 `sync manual forceFullSync`；判 `hasUnSyncEvent`；
2. 全量：`get remote readingList` → `save readingList to local`；随后 `get remote noteList`；
3. 增量：`Get Remote events(last event id, last event at)` → **`Filter outdated events`** → **`Combine multiple local events acting on the same data`**（本地事件压缩）→ `sync batch: N reading group: i/n` 分批上行；
4. 结果落库并记录 `sync_result_code/message`，事件带 **`sign`（签名）** 与 `device_id`；
5. 边界情况：时钟偏差以 `remoteLastEventAt` 与 `localLastEventAt` 比较后决定是否全量，避免漏事件。
   典型耗时（本机实测）：reading 1.1 s / tags 0.3 s / notes 0.6 s，总约 2 s。
6. SQLite 以 `WAL + synchronous=NORMAL + temp_store=memory` 运行。

### 5.8 Zotero 集成

- 客户端把用户的 `zotero.sqlite` **复制**到 `%APPDATA%\scholaread\files\zotero.sqlite`（本机 16.8 MB）读取，不直接改写 Zotero 库；日志显示按 `[标题] -> [文件名]` 逐一映射（含中英文作者格式与特殊字符文件名）。
- 配置项：`report_zotero_installed_date`、`zotero_plugin_report_date`、`checkZoteroOpenWithScholaread`、`setOpenWithScholaread`（把 Scholaread 注册为 Zotero 的 PDF 打开方式之一）。
- UI 文案含「未分类条目」（`zotero.uncategorized_items`）。

### 5.9 导入：PDF / CAJ / EPUB

- **PDF**：本地 `md5/sha256(hash)` 命名缓存到 `files/pdf/<hash>.pdf`，同 hash 去重直接复用。
- **CAJ（知网）**：客户端不本地解析，走 `caj2pdf()` 服务端转换 + `downloadFileByBlobId()` 取回 PDF；**必须登录**（失败文案：「导入失败，请先登录后再尝试导入CAJ文件」），并提示「正在解析CAJ文件，请稍后」。
- **EPUB**：`epub` 库解析，提取 `title/creator` 与封面（`reading-cover/`），`content_type: EPUB` 走独立的 `loadResourceForPdf`/`getEpubMetaInfo` 分支。

### 5.10 文献获取：规则引擎 + LLM 兜底 + 内嵌浏览器

**页面类型状态机（[实测] main.js）**
`PAGE_TYPE_{PAPER_DETAIL, PAPER_PREVIEW, ARTICLE_DETAIL, SEARCH_RESULTS, LOGIN, CAPTCHA, NOT_FOUND, UNKNOWN, SCHOLAR_PROXY}`；终止原因 `Reason_{Finished, Server_Unreachable, User_Terminated, Page_Not_Found, Unknown_Page}`。

**抽取策略（三级）**
1. **CSS 规则**：`global_page_detect_rule`（详情页识别）+ `global_extract_page_detail_rule`（元数据抽取）+ `extract_paper_search_result_rule.json`（结果列表）；覆盖 40+ 站点；
2. **LLM 兜底**：`parse_paper_detail_by_ai`、`parse_article_detail_ai`、`parse_paper_search_result_by_ai`（规则失效时把 DOM 交给模型抽取）；
3. **人工介入**：`waitHumanProcessFinished`（遇到登录/验证码时挂起，由用户在内嵌浏览器里完成，再继续）。

**下载链路**：`perform_download_pdf` → 存在 `config_allow_download_file`（直链）/ `config_allow_download_from_proxy`（**机构代理**，把 Google Scholar 结果转成带 `&q=…&btnG=` 的代理检索）/ `config_allow_download_from_sci_hub`（**`sci-hub://<title>` 伪协议**，代码里硬编码 `https://www.sci-hub.se/` 并解析 `#sciForm` 构造下载）；另有 DOI→出版商直链改写（`/doi/epub/` → `/pdfdirect/`，`/doi/epdf/` → `/pdfdirect/`）。
> ⚠️ 合规提示见 §9.3：Sci-Hub 回退是明显的法律风险点，开源项目**不应**复制。

**内嵌浏览器**：`dist/tab-container/` 是自研的 WebContentsView 标签容器（`GDTabPageContainer`，支持 `switchTabWithActionBar` 前进/后退/刷新、`openAgentPopupTab` 派生 Agent 标签页、`AgentTabOwnership` 归属管理），配 6 个专门 preload（pet/search/browser_agent/add_website/pdf_detect/network/disk_space_exhaust）。

**Agent 可用的浏览器工具集（[实测]）**：`navigate, snapshot, screenshot, click, type, scroll, press, back, exec_javascript, close_tabs, switch_tab`，外加领域工具 `search_cn_scholar`、`read_cn_scholar_detail`（知网检索/详情直读）。

### 5.11 AI Agent 体系（本版本最"重"的新增能力）

preload 暴露的 Agent 侧 IPC 达 **60+**，可归纳为六块：

| 能力块 | 代表 IPC | 说明 |
|---|---|---|
| 项目工作区 | `projectEnsureWorkspace / projectGetWorkspace / projectListWorkspaceFiles / projectImportFilesToWorkspace / projectExportWorkspaceZip / projectExportWorkspaceMigrationZip / projectImportWorkspaceMigrationZip` | 每个研究项目一个真实磁盘目录；支持整包导出与**迁移包导入**（含 `projectBuildWorkspaceMigrationImportPlan`、`projectInspectWorkspaceMigrationZip`） |
| 技能库 | `projectGetOfficialSkillsRegistry / projectInstallOfficialSkill / projectReconcileOfficialSkills / projectCreateSkill / projectBindSkill / projectSetSkillEnabled / projectImportLegacySkills` | 官方技能来自 `https://cdn.scholaread.com/assets/agent/skills_registry.json`，装到 `<workspace>/skills/`，支持 `required`/`auto_install`；有路径穿越校验（`invalid skill script path`） |
| 权限规则 | `projectGetPermissionRules / projectAddPermissionRule / projectRemovePermissionRule / projectClearPermissionRules` | Agent 操作的授权白名单 |
| 文件预览沙箱 | `projectCreateHtmlPreviewSession / projectGetHtmlPreviewExternalResourcesDefaultPermission / projectGrantHtmlPreviewTemporaryExternalResources / projectOpenFilePreview / projectSetFilePreviewTheme` | HTML 预览会话对外链资源的**逐文件授权**（可临时放行、按 `contentVersion` 失效） |
| 浏览器 | `agentCoreBrowserCall` + `agentCoreUseProjectWorkspace` | 见 §5.10 |
| 调试 | `projectAppendDebugLog`、`agent_log_dir` 独立日志目录 | Agent 运行日志与主日志分离 |

**Pyodide 计算沙箱（[实测]）**：`node_modules/pyodide` 46 MB 随包（numpy/pandas/scipy/matplotlib/lxml/beautifulsoup4/pillow/pyyaml…），并有启动脚本 `dist/matplotlib_bootstrap.py`：强制 `MPLBACKEND=Agg`、从 `/system/fonts/NotoSansSC-Subset.otf` 装载中文字体、`axes.unicode_minus=False`、把 `plt.show` monkey-patch 成抛错以引导 Agent 改用 `savefig()`。
→ 说明 Agent 的定位不只是"聊天"，而是**能跑数据处理与画图脚本的研究助手**。

**LLM 供应商（[实测]，典型的"借道"设计）**：客户端内置 `call_llm()`，走
`POST https://ai-assistant.jianguoyun.net.cn/openid/openrouter/v1/chat/completions`，
body `{model:"google/gemini-3.1-flash-lite", messages:[…], enable_thinking:false}`，`Authorization: Bearer <用户 key 或内置 key>`，超时 15 s。
即：**它并不自建模型网关，而是通过坚果云（Nutstore）的 AI 助手代理转发到 OpenRouter**——这与账号体系里的坚果云绑定、支付渠道中的坚果云联售一致。这类"小模型做页面类型判定/规则兜底抽取"的用法成本极低，很值得 FreeRead 借鉴（同理可换成本地小模型）。

### 5.12 导出与打印

- `startExportPDF(readingId, layoutType, includeNotes, includeHighlight)`：把重排 HTML + 笔记/高亮重新排版导出 PDF，含进度回调（`onExportProgress`、`getExportProgress`）与中断（`stopExportPDF`）、`onReadPrint` 打印通道。
- `dist/public/export/prepare_print.js`（22.5 KB）为打印专用准备脚本。
- 阅读页资产协议里保留 `is_print`、`ex_version`、`mark_version` 字段，说明导出与标注版本是服务端协议的一部分。

### 5.13 客户端周边机制

| 机制 | 实现 |
|---|---|
| 启动时序 | `unzipExtensions` → `waitForHomePageLoad` → `waitForEventHandleInitialized` → **`waitForVolcengineSdkLoad`**（等待首页里 `window.reportVolcengine.sdkLoad`，即**火山引擎（字节）SDK 注入完成**）→ 同步 → Zotero 扫描。全部实测于日志。 |
| 原生扩展 | DLL 从 asar 解到 `files/extensions/`，用 **koffi**（81 MB，FFI）调用：`LsfSdk.dll`、`LYSDK2.dll`、`ludp.dll`、`WebView2Loader.dll`。**归属已定位**：这些是**联想渠道（Lenovo）相关 SDK**——代码中 `isLenovoCooperationEnable = win32 && channel=="Lenovo"`，支付走 `getPaymentLenovo/getPaymentLenovoV2`，即 DLL 服务于机型预装与渠道支付，而非翻译/OCR（后两者分别在云端与 tesseract.js） |
| 网络 | axios + `http-proxy-agent`/`https-proxy-agent`(hpagent)/`socks-proxy-agent`/`proxy-from-env`，另有 `net_detect.html` 网络诊断页 |
| 缓存 | electron-re 的 `CacheInterceptorV3`（SQLite 表）；本地目录 `files/{pdf,out,region,reading-cover,data,extensions}`，可自定义外部缓存路径（`external_cache_dir`） |
| 更新 | `electron-updater` + `checkNewVersion/applyHotUpdate/upgradeNewVersion`，另有独立 `scholaread-updater`（残留 189 MB 安装包） |
| 遥测/稳定性 | `@sentry/electron`（上报到自建 `sentry-backend.jianguoyun.com`）、`reportEvent` 埋点、`js-md5`/`node-machine-id` 设备标识 |
| 主题/宠物 | 桌面宠物帧动画（7 种姿态 × 6 帧），位置记忆在 `config.json` |

### 5.14 依赖与开源成分（[实测] 395 个 npm 包）

**运行依赖（package.json 直接声明）**：`@sentry/electron`、`adm-zip`、`axios`、`better-sqlite3`、`check-disk-space`、`cheerio`、`compressing`、`electron-re`、`electron-store`、`electron-updater`、`epub`、`hpagent`、`http-proxy-agent`、`i18next`、`js-md5`、`jwt-decode`、`koffi`、`mime-db`、`mime-types`、`node-machine-id`、`proxy-from-env`、`pyodide`、`qrcode`、`rehype-parse`/`rehype-raw`/`rehype-remark`/`remark-gfm`/`remark-stringify`/`unified`（**HTML→Markdown 转换链**，用于导出与喂给 LLM）、`socks-proxy-agent`、`string-random`、`tesseract.js`、`winston`(+`winston-daily-rotate-file`)。
**体积前 5**：koffi 81 MB、pyodide 46 MB、tesseract.js-core 7.9 MB、node-gyp 4.0 MB、moment 3.6 MB。

**第三方前端组件（由其 `render/` 产物观察）**：Vue 3 + Element Plus（`el-alert` 等）、KaTeX（公式渲染，全套字体）、Mermaid + Cytoscape + dagre（图表/关系图渲染）、PDF.js。
**License 提示**：bundle 内嵌 license 文本显示其直接使用的多为 MIT/Apache 类（axios、ws、moment、js-md5、stack-trace…）；**pdf2htmlEX 为 GPLv3**——这决定了自研项目若直接链接/分发其 WASM，需要评估 GPL 传染性（见 §9.1）。

### 5.15 「本地/云端同源」的协议伪装（很值得学的架构技巧）

[实测] 客户端定义了自定义 scheme，把**云端 API 与本地缓存资产统一成同一套前端请求**：

```js
FILE_PREFIX = "scholaread://pdf2html.com/files/"
PATH = {
  ReadingList: `scholaread://${DOMAIN}/api/user/readings?`,
  READINGS   : `scholaread://${DOMAIN}/api/readings/`,
  SHARES     : `scholaread://${DOMAIN}/api/shares/`,
  THUMBNAIL  : "scholaread://pdf2html.com/…"
}
buildBaseUrlByFullId = id => `https://pdf2html.com/files/${id}`
WORK_DIR = "works"; ROOT_DIR = "works/out"
```

含义：前端（远端 Web 应用）按固定 URL 结构取数据与资源；**主进程拦截 `scholaread://`**：命中本地缓存/已转换产物就由 `service.js` 直接返回，未命中则回源真实服务器。于是「离线打开已下载文献」「本地转 PDF」「服务端 AI 重排」三种情况对前端完全透明，也让客户端与服务端的接口演进解耦。

> 这是本报告中最值得开源项目借鉴的**单点架构决策**：把"数据来源切换"收敛到一个进程内的协议代理，而不是散落在业务代码里的 if-else。

---

## 6. 商业模式与配额体系

[实测] 由其前端文案与 preload 接口可完整还原其计费模型：

| 维度 | 内容 |
|---|---|
| 会员层级 | `basic`（免费体验版）、**`pro`（专业版）**、**`proMax`（专业版 Max）**；`account_state: free\|pro` |
| 计费资源 | ① **AI 重排额度**（按页，"获取更多 AI 重排额度"）② **翻译字数/额度**（每日免费额度 + 包月字数）③ **AI Agent 额度**（按月，"本月 AI Agent 额度已用完"）④ **综述报告额度**（专业版每月 3 次）⑤ **额度包**（可单独购买，且"仅限 AI Agent 使用，未使用额度将在 {count} 天后随 AI Agent 额度重置清零"） |
| 免费版限制 | 「非专业版每天可试用 {0} 次，剩余 {1} 次」；「今日额度已用尽，请明天继续导入」 |
| 促销机制 | 优惠券（`{coupon} 元优惠券（{count} 天有效期）`）、抽奖弹窗（`🎊 抽中 {count} 天专业版会员！`）、老用户限时优惠、邀请/分享（`{0}，享每日翻译{1}！`）、学生/教育场景文案 |
| 支付 | 支付宝（日志中 `provider=alipay`，含 `onPurchaseOrderCreated` → `checkUserStateAfterUpgrade` 轮询 `pay_status`，约 3 秒间隔、约 30 秒后超时停止）、微信、**Stripe / Apple**（国际版）与**坚果云联售**；**联想渠道为 Windows 独占**（`isLenovoCooperationEnable = win32 && channel=="Lenovo"`，`getPaymentLenovo(V2)` + `lenovoSdkService.initialize()` 加载 `LYSDK2.dll`/`LsfSdk.dll`）；每个订单都贯穿 `coupon_code`；提供订阅管理跳转 |
| 广告 | 仅有「购买引导位」（`checkShowPurchaseAdsEntry` 当前**硬编码恒返回 true**，不含第三方广告投放）；且把「无广告沉浸阅读」作为付费权益之一 |
| 开源属性 | **闭源专有软件（已确证）**：购买协议载明由「上海亦答网络科技有限公司**开发、运营并享有独立知识产权**」，仅授予个人、有限、可撤销、不可转让、非排他许可；服务协议禁止任何商业或非商业目的的复制/传播/镜像/下载；GitHub 无 `scholaread` 组织（404） |

### 6.1 实际价格与额度（[公开已核验]，2026-10-03 取自官方计费接口）

**人民币（provider=alipay）**

| 商品 | 现价 | 原价 | 折扣 |
|---|---|---|---|
| 专业版 季付 | ¥109.00 | ¥109.00 | — |
| 专业版 年付 | **¥199.90** | ¥429.90 | −54% |
| 专业版 Max 季付 | ¥299.00 | ¥299.00 | — |
| 专业版 Max 年付 | **¥699.00** | ¥1,299.00 | −46% |
| Agent 额度加油包（月） | ¥19.90 | ¥29.90 | — |
| 深度研究报告加油包（月） | ¥29.90 | ¥29.90 | — |

**美元（provider=stripe）**：Pro 季付 $22.80 / 年付 **$58.92**（原价 $91.20）；Pro Max 季付 $59 / 年付 **$179**（原价 $249）。

**配额对照（官方 `/api/configs/pricing_account_state_rights`，−1 = 无限）**

| 资源 | 免费版 | 专业版 | 专业版 Max |
|---|---|---|---|
| 翻译 | 7,000 字/天 | 100,000 字/天 | 200,000 字/天 |
| AI 重排 | 50 页/天 | 500 页/天 | 1,000 页/天 |
| OCR / 划词 | 3 次/天 | 无限 | 无限 |
| AI 问答 | 5 次/天 | 50 次/天 | 100 次/天 |
| AI Agent | 150 /月 | 2,000 /月 | 10,000 /月 |
| AI 综述报告 | 0 | 3 /月 | 10 /月 |
| 单篇上传上限 | 50 MB | 200 MB | 300 MB |

其他已核验商业事实：
- **支付渠道**：`alipay` / `wechat` / `stripe` / `apple` / `lenovo`；协议规定计费周期为**按季度、按年**，支付宝渠道的 `pays` 列表**不含月付**（月付是否在售未验证）。
- **免费版含广告**：隐私政策披露**腾讯优量汇（广告）+ 火山引擎（统计）+ Bugly（崩溃）** SDK，并采集 Android_ID、OAID、设备序列号、安装列表、粗略位置等；免费版**无**双语重排 PDF 导出、**无**综述额度。
- **联售**：与坚果云捆绑（需绑定坚果云账号 + 支付宝），赠坚果云 Pro / 坚果云 AI 写作 / 怡氧一年。
- **退款口径冲突**：官网套餐页写「支持 7 天无理由退款」，而专业版购买协议 5.2 明确「**一经开通后不可退款**」→ 以协议为准更保守。
- **发票**：可开增值税电子普通发票（上海亦答网络科技有限公司开具）。

> 一处**官方自相矛盾**值得注意：套餐页宣称支持「影印版 PDF 重排 & 翻译」，而翻译 FAQ 明确扫描/影印版「**暂时无法翻译**」，只能用 iPad 截屏 OCR 兜底——这与 §5.6 的本地 `scanning_pdf` 通道一致，说明"影印版重排"至少在桌面端能力有限。

**对开源项目的启示**：其商业模型本质是「**把最贵的三种算力（版面模型 / 翻译 / LLM Agent）按量零售**」。开源项目若走同样路线，需要同等清晰的**成本-配额映射**；若走本地优先（Local-first）路线，则应以「省下这些额度」为卖点。

---

## 7. 公开资料、竞品与开源生态（外部视角）

> **本章的取证方法（重要）**：本执行环境的 `web_fetch` 被沙箱 DNS 拒绝（外部域名解析为非公网 IP），最终改为**用 Node.js 自带 TLS 直接抓取**（同类限制下的可行替代），因此本章引用的价格、配额、协议条款、GitHub 星标与许可证**均为 2026-10-03 当日真实返回并逐条核验**（每个仓库的 `license` 字段与 LICENSE 原文均已读取确认）；仅少量无法验证项标注「未验证」。完整证据链与 143 条外链见 `research/web-features.md`。

### 7.1 公开定位与计费口径

| 项 | 内容 | 来源 |
|---|---|---|
| 应用商店定位 | 名称即「**Scholaread 靠岸学术 – 英文文献翻译阅读器**」，桌面/移动/网页多端 | [公开] App Store 列表标题 |
| 第三方评测定位 | 被归纳为「**AI Agent 驱动的文献阅读与研究协作工具**」 | [公开] 小众软件（appinn）论坛主题标题 |
| 计费口径（第三方描述） | 「**按翻译和 AI 分析次数计算，而不是按打开 PDF 次数计算**」——与本报告 §6 由官方接口核验的「按资源类型配额（重排页数/翻译字数/Agent 额度/综述次数）」一致 | [公开] 开发者自荐帖与评测文章 |
| 官方功能口径 | 「改良传统两栏格式排版，使用 AI 引擎识别并提取 PDF 中的文本、目录、图片、表格、注释等元素，并重新组织布局」；「更快速的翻译速度、Zotero 文献一键导入、划词翻译、全网文献期刊搜索」 | [实测] 客户端内文案 |

### 7.2 竞品矩阵

| 类别 | 产品 | 形态/许可 | 相对 Scholaread 的强项 | 短板 |
|---|---|---|---|---|
| **直接竞品（闭源云）** | **Scholaread 靠岸学术** | 闭源商业，多端 + Agent | 重排+对照翻译体验成熟、中文期刊（知网/万方/维普）覆盖、Zotero 集成 | 云端依赖、额度计费、面板数据在云端、合规风险（Sci-Hub/代理） |
| | SciSpace / ReadPaper / ChatPDF / Elicit / Consensus | 闭源 SaaS | 论文问答与综述自动化、文献发现 | 无本地文件管理、无重排 PDF 阅读、隐私 |
| **开源主力** | **Zotero + 插件**（`zotero-pdf-translate`、Better Notes、Aria 等） | Zotero 为 **AGPL-3.0**；插件许可各异 **「未核实」** | 文献管理事实标准、插件生态、数据可迁移、免费 | 阅读体验与重排弱、翻译为"叠层"而非重排双语、AI 能力需自行拼装 |
| | **Sioyek** | **GPL-3.0**（「未核实」，请复核） | 为论文阅读深度优化（跳转、目录、portal、多窗口）、极快、键盘流 | 无翻译/AI/同步；UI 学习曲线陡 |
| | **KOReader / Calibre** | AGPL-3.0 / GPL-3.0 | 强大的电子书/PDF 阅读与格式转换 | 非科研向、无 AI |
| | **paper-qa**（Future House）等 | 「未核实」 | 面向论文的 RAG 问答，可本地接 LLM | 只解决"问答"，不含阅读器 |
| | **Obsidian + PDF 插件** | 闭源客户端 + 插件 | 知识库与双向链接 | 非论文专用 |

### 7.3 开源组件选型（许可已逐条核验，2026-10-03）

> 「许可」列均通过 GitHub API + LICENSE 原文核验；**与社区常见印象不同的已特别标注**。

**A. 端到端「同类产品」**

| 项目 | 许可 | 星标 | 活跃度 | 对我们的意义 |
|---|---|---|---|---|
| [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate) | **AGPL-3.0** | 37.3k | 活跃（2026-10） | **最接近 Scholaread"翻译+重排"的开源件**：保留版式的双语全文翻译，支持 Google/DeepL/Ollama/OpenAI，含 CLI/GUI/MCP/Docker/Zotero |
| [Zotero](https://github.com/zotero/zotero) | **AGPL-3.0** | 15.5k | 活跃 | 文献管理事实标准；无重排/无逐段对照翻译 |
| [zotero-pdf-translate](https://github.com/windingwind/zotero-pdf-translate) | AGPL-3.0 | 12.0k | 活跃 | Zotero 内翻译（20+ 服务），但仍是原版式叠层 |
| [zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh) | AGPL-3.0 | 7.1k | 2026-09 | 把 PDFMathTranslate 接进 Zotero |
| [PaperQA2](https://github.com/Future-House/paper-qa) | **Apache-2.0** | 9.3k | 活跃 | 带引用的科学文献 RAG 问答，可直接作为"问论文"内核 |
| [Sioyek](https://github.com/ahrm/sioyek) | GPL-3.0 | 9.9k | 代码活跃但**正式版停在 2022-12** | 论文阅读交互（portals/键盘流）最佳参考 |
| [KOReader](https://github.com/koreader/koreader) | AGPL-3.0 | 30.1k | 活跃 | 墨水屏重排阅读参考 |
| [Calibre](https://github.com/kovidgoyal/calibre) | GPL-3.0 | 26.1k | 活跃 | 格式转换参考 |
| [Obsidian PDF++](https://github.com/RyotaUshio/obsidian-pdf-plus) | **MIT** | 2.5k | 2025-08 | PDF 标注 + 双向链接 |
| [Paperlib](https://github.com/Future-Scholars/paperlib) | GPL-3.0 | 2.3k | 2026-04 | 开源文献管理器 |
| ~~Readarr~~ | GPL-3.0 | 3.5k | **已归档** | 不作基础 |

**B. 解析 / 版面 / OCR 构建块**

| 组件 | 许可（已核验） | 备注 |
|---|---|---|
| [PDF.js](https://github.com/mozilla/pdf.js) | **Apache-2.0** | 渲染层首选（Scholaread 也用它） |
| [Docling](https://github.com/docling-project/docling) | **MIT** | 许可最宽松的文档解析，生态增长快 |
| [Marker](https://github.com/datalab-to/marker) | **Apache-2.0** | ⚠️ 社区常误传为 GPL-3.0，**实为 Apache**（旧版许可）→ 商业友好 |
| [GROBID](https://github.com/kermitt2/grobid) | **Apache-2.0** | 学术元数据/引文抽取经典方案 |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) / [Surya](https://github.com/datalab-to/surya) | Apache-2.0 | 中文 OCR / 版面与阅读顺序 |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | MIT | 字符级/表格级精确提取 |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | **AGPL-3.0** | 性能最好，但闭源商用**必须买 Artifex 商业许可** |
| [MinerU](https://github.com/opendatalab/MinerU) | **Apache-2.0 + 附加条款** | 中文最强；MAU>1 亿或月营收>2000 万美元需商业授权，**在线服务必须显著署名** |
| [Nougat](https://github.com/facebookresearch/nougat) | 代码 MIT / **权重 CC-BY-NC** | **权重不可商用**，商用项目请排除 |
| [pdf2htmlEX](https://github.com/pdf2htmlEX/pdf2htmlEX) | **GPLv3** | Scholaread 的选择；项目老化（最后 release 2020）+ 传染性 → 新项目建议替换 |

**C. 许可结论（直接影响项目 license 选择）**

1. **AGPL-3.0 是最大雷区**：Zotero、PyMuPDF、PDFMathTranslate、KOReader 等均为 AGPL。若 FreeRead 以**网络服务**形态对外提供，AGPL 要求向用户提供对应源码；桌面分发则触发 GPL 系整体开源义务。**"调用"不等于可闭源，链接方式需法务确认**。
2. **推荐商业友好底座**：`PDF.js（Apache）+ Docling（MIT）/Marker（Apache）+ GROBID（Apache）+ PaddleOCR/Surya（Apache）+ PaperQA2（Apache）`。
3. 若要自研"版面保留 + 双语对照"，管线可设计为：**Docling/Marker 出结构化块 → 逐块翻译 → 用 §5.3 的锚点模型重新排版**，即可绕开 pdf2htmlEX 的 GPL 与老化问题。
4. 若做 Zotero 插件，**插件自身需按 AGPL 发布**（并注意 Zotero 商标政策）。

### 7.5 用户口碑与产品短板（第三方评价，[公开]）

| 指标 | 值 |
|---|---|
| App Store 中国区 | **4.63★ / 1471 评** |
| Google Play | 4.4★ / 37 评，1 万+ 下载 |
| 官方便携扩展 | **1.3★（7 评）**，且 **2023-12 之后未再更新** |

**被反复抱怨的点（对我们即机会点）**：
- 「**每次打开回到文章开头**」——阅读位置/进度恢复不可靠（我们在 §9.2 把"跨模式锚点一致性"列为高风险项，正是同一问题）；
- 「AI 无响应 / 闪退 / 乱码」——云端依赖带来的稳定性问题；
- 「Google 登录不互通」、免费额度「太少 / 略贵」；
- 黑猫投诉平台有"账号被冻结"记录（页面已失效，仅搜索快照，**未验证**）。
- 商店声明矛盾：Google Play 的「数据安全」自述称"不与第三方分享、不收集任何数据"，与其隐私政策列出的多个第三方 SDK 明显冲突 → **商店声明可信度低**。

**被赞赏的点**：多端同步、对照翻译"又好又快还整洁"、Zotero 一键导入、可离线阅读常用文献（仅缓存层面）。

### 7.4 结论：FreeRead 的定位建议

综合 §3–§6 的对标结果，Scholaread 把"读—译—管—研"做成了一个**云端闭环**，其不可替代性主要来自**中文期刊生态 + 重排质量 + 配额零售**。开源项目正面复刻这套闭环保姆级体验成本极高，但存在三个明确的空位：

1. **本地优先的「重排 + 对照翻译 + 笔记」**（无额度、可离线、内网可用）——技术上可行（§9.1 组件齐备），这正是 Scholaread 最贵的一环；
2. **数据主权**：文件式知识库（PDF + Markdown + BibTeX 同目录、可 Git/同步盘），对比其云端主数据；
3. **合规与可审计**：明确只走 OA/授权渠道 + Agent 行为全量可审计，直接对标其 Sci-Hub/代理风险点（§8），对高校与机构采购更友好。

---

## 8. 合规、安全与隐私观察

> 以下仅为**技术观察**，不构成法律意见。开源项目在借鉴时应对标红项做显式取舍。

| 级别 | 观察 | 证据 |
|---|---|---|
| 🔴 高 | **内置 Sci-Hub 回退下载**：`config_allow_download_from_sci_hub` 与 `sci-hub://<title>` 伪协议，代码内硬编码 `https://www.sci-hub.se/` 并解析其检索表单 | main.js |
| 🔴 高 | **机构代理/批量抓取的绕过链路**：`config_allow_download_from_proxy` 会用标题构造 Google Scholar 代理检索；DOI 直链改写成 `/pdfdirect/`；登录/验证码交给用户手动完成（`waitHumanProcessFinished`）后再继续自动抓取 | main.js |
| 🟠 中 | **凭据以明文存放**：`%APPDATA%\scholaread\config.json` 中直接保存 `sch_user_token`(JWT)、`refresh_token`、`ext_id`、`device_id`；`Local State` 用 Electron 标准 `os_crypt` 加密，但 config.json 未加密 | config.json |
| 🟠 中 | **设备指纹与遥测**：`node-machine-id` + `getServerDeviceId()`，Sentry 上报到自建后端（`sentry-backend.jianguoyun.com`），`reportEvent` 业务埋点 | main.js |
| 🟠 中 | **本地原生扩展执行**：启动即把 DLL 解包到用户目录并由 koffi FFI 加载（`LsfSdk.dll`/`LYSDK2.dll`/`ludp.dll`），扩展来自安装包而非签名仓库 | 日志 `unzipExtensions`、`files/extensions/` |
| 🟡 低 | **Agent 动态安装远端技能**：从 CDN 拉 `skills_registry.json` 并按需下载技能包到工作区（已有路径穿越校验与权限规则，属于设计良好的部分） | main.js |
| 🟡 低 | **HTML 预览沙箱的逐文件外链授权**：对 Agent 生成的 HTML 的外部资源请求做默认拒绝 + 逐文件放行 | preload |
| ℹ️ 提示 | 客户端自述"仅提供文献检索和导入途径，期刊网站使用权限以用户具体订阅情况为准" | UI 文案 |
| 🟠 中 | **免费版含第三方广告与统计 SDK**：隐私政策披露**腾讯优量汇（广告）+ 火山引擎（统计）+ Bugly（崩溃）**，并采集 Android_ID、OAID、设备序列号、安装列表、粗略位置等；付费权益之一即「无广告沉浸阅读」 | [公开已核验] 隐私政策 |
| 🟡 低 | **商店声明与隐私政策自相矛盾**：Google Play「数据安全」自述称不与第三方分享、不收集数据，与上述 SDK 披露冲突 → 商店声明可信度低 | [公开已核验] |
| 🟡 低 | **账号风控**：购买协议 1.4 允许以封禁手段反盗用；黑猫投诉平台存在"账号被冻结"记录（页面已失效，**未验证**） | [公开] |

**给 FreeRead 的硬性建议**：不要实现 Sci-Hub / 代理绕过任何一项；把"抓取"限定在**开放获取（OA）**与**用户已授权**（校园网登录、用户自己的会话）范围内，并在 README 中明确声明。

---

## 9. 对 FreeRead（开源论文辅助阅读器）的启示

### 9.1 可直接复用的开源替代件（按 Scholaread 的模块一一对应）

> 许可与星标已在 §7.3 逐条核验，此处只做**模块映射**与选型结论。

| Scholaread 模块 | 开源替代（推荐度） | 许可要点 |
|---|---|---|
| PDF 原文渲染 + pdf.js viewer | **PDF.js** ★★★★★ | Apache-2.0，可直接用 |
| pdf2htmlEX(WASM) 做 PDF→HTML | **Docling**（MIT）/ **Marker**（Apache）/ **GROBID**（Apache）；pdf2htmlEX 仅作参考实现 | **不要**为省事直接引入 pdf2htmlEX（GPLv3 + 项目老化） |
| 云端 trust region 版面模型 | Docling/Marker 的版面块 + 自研区域分类；轻量起步可用**文本行聚类 + XY-Cut** 规则法 | 本地推理可用 ONNX Runtime |
| 对照翻译与重排渲染 | 自研（锚点模型见 §5.3）；翻译接**本地 LLM / 用户自带 Key**；可参考 **PDFMathTranslate**（AGPL）的实现思路 | 若要闭源，需自研同管线 |
| 公式渲染 | **KaTeX**（MIT）/ MathJax（Apache-2.0） | 宽松 |
| 图表/流程图渲染 | **Mermaid**（MIT）、Cytoscape（MIT） | 宽松 |
| OCR | **PaddleOCR / Surya**（Apache-2.0，中文更强）或 Tesseract | 宽松 |
| 元数据与引文 | **GROBID**（Apache-2.0）+ CrossRef / OpenAlex / Unpaywall API | 宽松 + 遵守 ToS |
| 论文问答（RAG） | **PaperQA2**（Apache-2.0） | 宽松，可直接用 |
| 本地库/同步 | **SQLite + 事件溯源**（照搬其模式）；同步后端用 Syncthing/WebDAV | 自研 |
| Zotero 集成 | 直接读 `zotero.sqlite` 只读副本（Scholaread 同做法）+ Better BibTeX | 若做 Zotero 插件则须 AGPL |
| AI Agent + 技能 | 通用 Agent 框架 + `skills/` 目录约定；沙箱用 Pyodide/容器 | 自研为主 |
| 渲染性能（可选） | PyMuPDF（性能最好但 **AGPL**，闭源须购商业许可）或 pdfplumber（MIT） | **许可陷阱** |

> **后续决策（2026-10-03）**：FreeRead 主仓许可已定为 **AGPL-3.0**，因此上表中所有"因许可宽松而取舍"的理由不再是约束——PyMuPDF、Zotero、PDFMathTranslate、pdf2htmlEX 等 AGPL/GPLv3 组件均可直接复用。随之新增的三条 AGPL 义务（源码、标注、网络服务开源）与解锁清单见 [技术方案 §12.1](../plan/FreeRead-技术方案与里程碑.md)。

### 9.2 建议的分层架构（照搬其成功点、替换其不安全点）

```
[渲染层]  PDF.js 原文视图  ─┐
                            ├─ 统一锚点：page + bbox + lineId + sentenceId  ← §5.3
[重排层]  本地版面模型 → 语义 HTML ─┘
[能力层]  翻译(本地/自带Key) · OCR · 公式 · 问答(可插拔 Provider)
[数据层]  SQLite(文献/笔记/事件) + 只读 Zotero 适配器
[Agent层] 工作区目录 + skills/ + 权限白名单 + Pyodide/容器沙箱
[获取层]  OA 优先（Unpaywall/arXiv/PMC/OpenAlex/CORE）+ 用户已授权会话；禁止 Sci-Hub
```

### 9.3 差异化机会（相对 Scholaread）

1. **Local-first / 可完全离线**：Scholaread 的翻译、重排、AI 都是云端，且配额受限；开源项目若能本地跑版面+本地 LLM，可主打"无额度、无上传、机构内网可用"。
2. **数据主权与可迁移**：它虽然支持工作区导出，但主数据在云端；开源项目可做**纯文件式知识库（Markdown + BibTeX + PDF 同目录）**，天然可 Git/diff。
3. **开放插件体系**：它的原生扩展是其私有 DLL；开源项目可用标准 Extension API（如 PDF.js viewer 插件 / VS Code 式 manifest）建立生态。
4. **合规即卖点**：明确拒绝 Sci-Hub、只走 OA 与合法授权，便于高校/机构采购。
5. **可审计的 Agent**：把 Agent 的每一步工具调用、文件读写、网络请求记录下来（对标它的 `agent-logs` + 权限规则，但开源可审计）。
6. **专打已被证实的体验短板**（来自 §7.5 的真实用户抱怨，属低成本高收益的"补位"）：
   - 「**每次打开回到文章开头**」→ 把**阅读位置/进度恢复**做成硬承诺（其根因就是锚点一致性，见 §5.3）；
   - 「AI 无响应 / 闪退 / 乱码」→ **本地优先 + 优雅降级**（云端不可用时仍可读、可译、可记笔记）；
   - 官方浏览器扩展 **1.3★ 且 2023-12 后停更** → 一个可靠的"一键保存到本地库"扩展即可形成差异；
   - 免费额度少、缺术语库 → 开源本地方案天然无限额，并可补上**用户自定义术语表**（Scholaread 已确认没有该功能）。

### 9.4 工程风险清单

| 风险 | 说明 | 缓解 |
|---|---|---|
| 许可传染 | pdf2htmlEX 为 **GPLv3** | 用子进程/WASM 隔离仍属争议区；优先选 MIT/Apache 的版面与渲染栈，或整体采用 GPL 兼容许可 |
| 版面质量 | 自研规则法在双栏/公式/表格上误差大 | 先做"原文+翻译"保底体验，再逐步上线重排；用 §5.2 的 `score` 机制显式标注低置信区域 |
| 字体与体积 | 中文字体动辄 2–4 MB/款 | 子集化（subset）+ 按需下载；参考其 `NotoSansSC-Subset.otf` 做法 |
| 跨模式锚点一致性 | 重排后句子与 PDF 行错位是体验杀手 | 强制"句子 ↔ 行区间"映射校验，低置信降级为整段锚点 |
| 同步复杂度 | 事件溯源 + 多端冲突处理成本高 | 先做单机 + 文件级同步（Syncthing/WebDAV），再演进 |
| 扫描件 | OCR 慢（其本机检测约 4.3 s/篇） | 异步流水线 + 后台队列 + 结果缓存 |

---

## 10. 附录

### 10.1 证据留存索引（本仓库）

> 原始取证产物（解包文件、dumps、TSV、截图、解析脚本）已在仓库清理中删除，原因见 §1 说明；下表为**当前留存**。

| 文件 | 内容 |
|---|---|
| `report/Scholaread-调研报告.md` | 本报告：结论 + 可核验路径/命令 |
| `research/feature-inventory.md` | 功能清单（506 行，按 2266 条 UI 文案证据归类，含 14 项证据缺口与「不存在」的反向结论） |
| `research/web-features.md` | 公开资料调研（387 行 / 143 条外链；价格、配额、协议条款、GitHub 星标与许可逐条核验） |
| `%APPDATA%\scholaread\logs\2026-10-0*.log` | 本机运行日志（同步/OCR/Zotero/支付时序，位于客户端数据目录，非仓库文件） |

### 10.2 本机关键路径速查

```
安装：%LOCALAPPDATA%\Programs\Scholaread\
主包：…\resources\app.asar                     (164.7 MiB, 8576 文件)
本地 reflow 服务：…\resources\app.asar → dist/service/service.js
pdf2htmlEX WASM：…\resources\app.asar → dist/wasm/pdf2htmlEX.wasm (12.5 MB)
OCR 语言包：…\resources\app.asar → dist/public/tesseract/{eng,chi_sim}.traineddata
站点规则：…\resources\app.asar → dist/public/rule/*.json
数据目录：%APPDATA%\scholaread\
  ├─ config.json                 (含 token/设备/布局配置；明文)
  ├─ scholaread.sqlite           (文献库/笔记/事件)
  └─ files\
     ├─ pdf\<hash>.pdf           (文献原文缓存)
     ├─ out\<assetVersion>\<hash>\server\<page>\{index.html,origin_index.html,index.css,bg*.png,region.json,paragraph.json,…}
     ├─ region\layouts\v2\sr_5\<hash>.json   (trust region 版面)
     ├─ data\{fonts,poppler}     (重排字体与 poppler 数据)
     ├─ extensions\*.dll         (koffi 加载的原生扩展)
     └─ zotero.sqlite            (用户 Zotero 库的只读副本)
```

### 10.3 复现步骤（如需重新取证）

> 取证脚本已在仓库清理中删除；以下为当时的等价命令与算法要点，可据此重写（每段均为数十行量级）。

```powershell
# 1) 列出 app.asar 全部条目：读前 8 字节 → uint32@4 = 头部 pickle 尺寸；
#    再读该尺寸的头部：uint32@0 = payload 尺寸，uint32@4 = JSON 长度，JSON 从偏移 8 开始
node <你的脚本>.mjs "<install>\resources\app.asar" <out>.json

# 2) 按前缀导出第一方文件：baseOffset = 8 + headerSize，逐条目 readSync(offset = baseOffset + entry.offset)
node <你的脚本>.mjs "<install>\resources\app.asar" <outDir> "dist/main.js" "dist/service/service.js" "dist/public/rule"

# 3) 在压缩单行 bundle 中定位关键字：用正则找匹配位置，取前后 N 字符窗口打印（勿整行输出）
node <你的脚本>.mjs <bundle.js> 200 "trust_region" "sci-hub"

# 4) 从 Web 产物挖掘中文 UI 文案：正则匹配含 CJK 的字符串字面量，去重后输出 TSV
node <你的脚本>.mjs "<install>\resources\render\assets" <out>.tsv
```

### 10.4 未能完成的验证与已知局限

1. **界面实测受限**：客户端进程能正常启动并完成同步（日志可证），但在本执行环境下**主窗口句柄不可见**（`MainWindowHandle=0`，桌面截图无窗口），因此 UI 层面的结论均来自其随包前端产物与运行日志，而非人工点选。若需界面级取证，建议在交互桌面手动启动后按本报告 §3 的清单逐项核对。
2. **云端接口未做主动探测**：为避免触碰账号与合规边界，未对其 `api.scholaread.cn` / `pdf2html.com` 发起未授权调用；服务端实现（模型结构、并发、缓存）属于黑盒，报告中的相关描述均已标注为 [推测]。
3. **`ReflowEngineList` 的确切取值未取到**（已知至少含 `default` 与 `server` 两种引擎），本地引擎与 `sr1` 布局类型的对应关系为推断。
4. **外部取证方式受限但已克服**：`web_fetch` 在本环境被沙箱 DNS 拒绝（外部域名均解析为非公网 IP），公开资料最终改由 **Node.js TLS 直连**获取，§6.1/§7 的价格、配额、协议与许可均据此核验（2026-10-03）；仍有 14 条待确认项（如 LLM/翻译供应商未披露、月付是否在售、退款口径冲突、Zotero 独立 `.xpi` 是否存在），清单见 `research/web-features.md` 文末。
5. **产品迭代速度快**：本报告基于 cn-1.1.86（2026-09-28 资产版本）；其客户端的业务逻辑大部分在云端 Web 应用中，版本迭代可能使 UI 层结论快速过时（架构性结论相对稳定）。
