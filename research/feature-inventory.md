# Scholaread（靠岸学术）桌面客户端 v1.1.86 功能清单（证据版）

> **归档说明（2026-10-03 仓库清理）**：本文是当时的**证据留档**。文中引用的原始产物——`research/web-strings.txt`（UI 文案 TSV）、`research/scan-main.txt` / `scan-service.txt`、`research/dist-tree.txt`、`research/asar-summary.txt` 以及 `research/asar/` 解包目录（含第三方专有代码）——**已全部删除，不在本仓库中**。因此文中的 `asar/...`、`web-strings.txt`、`scan-*.txt`、`dist-tree.txt` 等路径仅表示**当时的取证出处**，不代表仓库现存的文件；如需复核，请按 [`report/Scholaread-调研报告.md`](../report/Scholaread-调研报告.md) §10.3 的步骤在本机客户端重新取证。

> 分析对象：`Scholaread` Electron 桌面客户端 v1.1.86，appId `cn.scholaread.pc`，发行方「上海亦答网络科技有限公司」（`asar/package.json`：`"version": "1.1.86"`、`"appId": "cn.scholaread.pc"`、`"author": {"name": "上海亦答网络科技有限公司"}`、`"assetVersion": "20260928-1"`）。
>
> 证据来源与引用约定：
> - **主证据**：`research/web-strings.txt`（2266 条去重中文字符串，来源文件列已标注）。该文件绝大多数条目来自同一个 Web 前端产物 `main-0623db67.js`，文中简写为 **「web」**；少数来自 `index-48662636.js`（日期本地化）、`index-1d3f0da1.css`（字体）。
> - **客户端 locale**：`asar/dist/public/locales/zh.json`（简写 **zh.json**）、`en.json`。
> - **主进程/服务进程静态证据**：`asar/dist/main.js`、`asar/dist/service/service.js`、`asar/dist/preload*.js`、`asar/dist/tab-container/*`（简写 **main.js / service.js / preload.js / tab-container**）；汇总视图见 `research/scan-main.txt`、`research/scan-service.txt`、`research/dist-tree.txt`、`research/asar-summary.txt`。
> - **站点抽取规则**：`asar/dist/public/rule/extract_paper_detail_rule.json`、`extract_paper_search_result_rule.json`、`page_detect_rule.json`。
> - 引用一律保留原文字符串（含日文条目：同一前端包里中文条目缺失、只有日文条目时，用日文条目作为证据并说明）。
> - UI 文案中的 `@:general.srdName`、`@:general.brandName.*`、`@:accountPlan.*` 是 i18n 占位符（分别指产品名 / 第三方品牌名 / 套餐名），引用时原样保留。
> - 标 **「推测」** 的条目是仅有间接线索、未找到直接用户可见文案的能力。
> - 出于安全要求，本文**不复述**任何密钥、DSN、API Key 值，只说明其存在与归属。

---

## 1. 阅读与排版

### 1.1 重排模式 vs 原文模式

| 功能点 | 证据 |
| --- | --- |
| 两种阅读模式并存 | 「重排模式」／「切换至重排模式」／「原文」／「原文を表示」 |
| 原文模式的功能限制 | 「抱歉，这篇文章原文模式目前不支持翻译，请切换为重排模式翻译。」 |
| 重排模式是笔记/翻译的载体 | 「当前模式暂不支持，请去重排模式下做笔记。」；「请使用截图翻译或重排模式翻译此文章。」 |
| 重排=AI 解析 PDF 元素后重排 | 「改良传统两栏格式排版，使用 AI 引擎识别并提取 PDF 中的文本、目录、图片、表格、注释等元素，并重新组织布局，给你更流畅的阅读体验。」；「学术级 AI PDF 解析 & 重排」；「AI 排版」；「启用 AI 排版」；「开启 AI 重排」；「PDF 智能重排」 |
| 重排中的进度与失败 | 「努力重排中...」／「正在加载 AI 重排... {progress}」／「正在重转，稍后刷新...」／「抱歉，此论文排版转换失败」／「该文件转码失败」 |
| 影印版（扫描件）是独立文档类型 | 「影印版」／「影印版 PDF 重排 & 翻译」／「支持对影印版 PDF 进行解析、重新排版、翻译。」／「当前文章为影印版，部分功能可能无法使用。」／「您看到此提示，表明这篇文章可能是通过扫描设备对原始纸质文档进行拍摄后生成的电子文件。」／「您可以使用@:general.srdName阅读影印版文章，但可能会存在显示效果较差的情况，部分功能（如翻译、笔记、AI 解答等）可能无法正常使用。」 |
| 最大页数限制 | zh.json `reflow.failure.reachMaxPage`：「最多支持 {{max_page}} 页」；「AI 重排最多支持 {max_page} 页」；「AI 重排最大支持 {max_size}」；「AI 功能目前仅支持 {pages} 页及 {size} 内的文档」 |
| 引擎可切换（默认/AI 服务端引擎） | 「切换重排引擎：{engineName}」／「使用默认排版引擎」／「普通重排」／「使用普通重排」／「引擎切换失败，当前文档暂不支持」／「如等待时间过久，可切换至普通引擎。」／「影印版 PDF 转换较复杂，如等待过久，可使用普通模式」；代码侧 `getReflowEngineConfig`、`setReflowEngine`、`reflow_engine` 字段（main.js / service.js） |
| 排版纠错（人工标注区域后重新重排） | 「标记错误区域」／「调整区域」／「调整区域类型」／「调整区域顺序」／「调整区域位置及尺寸」／「区域颜色关联」／「改善重排」／「重新上传」／「保存 & 重转」／「点击后会将所有修改过的页面信息保存，然后基于新的区域信息重新生成重排页面。」／「然后按照期望的区域顺序逐个点击即可，点击“编辑”即可回到编辑模式。」／「可通过下拉框区域类型，如：“表格”、“公式”、“图表”等。」 |
| 排版错误类别（用户反馈维度） | 「布局错乱」／「排版有误」／「文本重叠」／「换行问题」／「尺寸不对」／「内容缺失」／「可标记“布局错乱”、“尺寸错乱”等错误类别，若无错误默认“无”。」 |

### 1.2 目录 / 大纲 / 图表目录

| 功能点 | 证据 |
| --- | --- |
| 目录（大纲）展示与生成 | 「目录」／「正在生成目录...」／「抱歉, 没有可用的目录。」／「目录无效，请重试。」／「未获取到有效目录，请重试。」 |
| 目录可翻译 | 「翻译目录」 |
| 图表/引文清单 | 「图表」／「暂无图表」／「引文与图表」／「表格」；日文条目「図表が見つかりませんでした」（未找到图表） |
| 当前定位与跳转 | 「定位到此处」／「回到顶部」／「跳转到底部」／「越过这条线」 |
| 目录/图表来自服务端或 EPUB 解析 | `service.js` 响应字段含 `catalogues:r,figures:c`；`buildCatalogueForEpub`（EPUB 目录构建）见 `service.js` |

### 1.3 段落 / 句子 / 双栏

| 功能点 | 证据 |
| --- | --- |
| 段落、句子粒度的显示设置 | 「句子数量」／「项目符号」／「文字显示设置」／「重点句子高亮」（「全文翻译、AI 导读、重点句子高亮……前往 {0} 体验更多功能。」）；**「推测」**：二者同属文本显示设置项，具体语义无更细文案 |
| 重点句子提取 | 「阅读重点」／「阅读重点提取中...」／「阅读重点提取失败」／「暂时无法提取重点句子」／「切换模式以查看 AI 提取的阅读重点」 |
| 双栏 | 未发现用户可切换的「双栏/分栏」开关；仅有一处把**原始 PDF 的双栏版式**作为重排对象：「改良传统两栏格式排版，使用 AI 引擎识别并提取 PDF 中的文本、目录、图片、表格、注释等元素，并重新组织布局」（web） |

### 1.4 字体 / 字号 / 视图 / 主题

| 功能点 | 证据 |
| --- | --- |
| 字号与字体可设置 | 「字号」／「选择字体」／「文字显示设置」／「AI 问答字号」／「调整 AI 回复文本字号」／「AI 回答フォントサイズ」 |
| 字体栈含微软雅黑 | `index-1d3f0da1.css` → 「微软雅黑」 |
| 视图密度/形态 | 「宽屏视图」／「默认视图」／「视图设置」／「卡片视图」／「切换至卡片视图」／「表格视图」／「布局选项」／「布局」／「排版」 |
| 暗色模式 | 「深色模式」／「浅色模式」／「跟随系统」／「界面主题模式」／「画面テーマモード」；`tab-container/index.html` 使用 `color-scheme: light dark` 与 `@media (prefers-color-scheme: dark)` |
| 翻译结果可视装饰 | 「显示译文下划线」／「訳文の下線を表示」 |

### 1.5 翻页 / 滚动 / 缩放 / 阅读进度与统计

| 功能点 | 证据 |
| --- | --- |
| 基础阅读操作 | 「放大」／「缩小」／「缩放页面」／「适应屏幕宽度」／「适应屏幕高度」／「全屏显示」／「退出全屏」／「向左旋转」／「向右旋转」／「水平翻转」／「垂直翻转」／「在新窗口打开」／「已在新窗口打开」／「別ウィンドウで開く」 |
| 翻页/滚动底层组件 | 内置 pdf.js 完整 viewer：`dist/public/pdfjs/web/viewer.html`、`viewer.mjs`、`viewer.css`（`dist-tree.txt`），含 `secondaryToolbarButton-scrollPage/scrollVertical/scrollWrapped` 等图标 → 具备翻页与滚动两类浏览方式 |
| 阅读进度 | 「阅读进度」／「已读 {currentPages}，共 {totalPages}」／「未读，共 {totalPages}」／「已读完」／「继续阅读」／「上次阅读」／「阅读状态」／「阅读中」 |
| 阅读统计（时长/页数/次数） | 「阅读时长」／「{count} 页」／「每天 {quota} 页」；`service.js` 阅读对象含 `read_progress`、`read_point`、`read_state`、`read_time`、`read_count`、`read_days`、`read_at`（`buildReadingResponse`） |
| 阅读数据跨端同步辅助 | 「电脑、平板、手机，多设备数据同步、实时跟踪阅读进度、保存阅读数据。」；`updateReadingOpenTime`、`getLocalReadingDataByFileName`（`preload.js`） |
| 分页/滚动偏好（推测） | 未找到「翻页模式/滚动模式」文案；**「推测」**：阅读器复用 pdf.js viewer 默认的滚动/分页两种呈现，但无产品化开关文案 |

---

## 2. 翻译

### 2.1 翻译模式

| 模式 | 证据 |
| --- | --- |
| 对照式翻译（双语对照、逐段对照） | 「对照式翻译」／「対照翻訳」／「双语对照」／「全文对照翻译」／「自动逐段对照翻译，轻松理解文献核心观点和支撑论据，突破语言障碍。」／「双语重排」相关：「导出双语重排 PDF」 |
| 仅译文 / 仅原文 | 「仅译文」／「仅原文」／「译文」／「原文」／「显示原文」 |
| 全文翻译开关 | 「全文翻译」／「文章全文翻译」／「翻译内容」／「启用 AI 全文翻译」／「开启后，自动显示全文译文」／「免费启用翻译」／「無料で翻訳」／「翻訳を有効にする」 |
| 划词翻译 | 「OCR 翻译、划词翻译」／「更多翻译模式选择：OCR 翻译、划词翻译等」／「更快速的翻译速度、Zotero 文献一键导入、划词翻译、全网文献期刊搜索……」／「支持 iOS 中的 OCR 截图翻译和电脑客户端中的划词翻译和 OCR 截图翻译。」；实现线索：`getTranslate`（`preload.js`）、`handleGetTranslate`（`main.js`） |
| 截图 OCR 翻译 | 「截图翻译」／「OCR 翻译」；实现线索：`getCapture`（`preload.js`，`main.js` 中 `handleGetCapture` 走 `webContents.capturePage()` 生成 jpeg）、内置 tesseract 语言包 `dist/public/tesseract/eng.traineddata`、`chi_sim.traineddata`，`main.js` 中 `createWorker(["eng","chi_sim"], …)` |
| 翻译消耗额度提示 | 「使用截图翻译会消耗翻译额度。非专业版每日试用次数自动重置，无法累加无法积累、兑换、折现或返还，请及时使用。」／「需使用您的翻译额度。」 |
| 未登录拦截 | 「请登录后使用翻译功能」／「翻訳を利用するためには、サインインしてください」 |

### 2.2 语言设置

| 功能点 | 证据 |
| --- | --- |
| 目标语言选择 | 「翻译语言」／「设置默认目标语言」／「选择语言」／「将原文翻译为」／「原文を以下の言語に翻訳」 |
| 语言清单（19 条语言名，含「繁体中文」「繁體中文」两种写法） | 「简体中文」「繁体中文」「繁體中文」「英语」「日语」「韩语」「法语」「德语」「西班牙语」「葡萄牙语」「意大利语」「俄语」「阿拉伯语」「波斯语」「荷兰语」「泰语」「越南语」「印尼语」「马来语」 |
| 源语言自动检测与冲突提示 | 「检测到{language}」／「检测到翻译语言与文章语言相同。」／「翻訳言語と文章の言語が同じであることが検出されました。」／「仍要翻译？」 |
| 界面语言与回答语言分离 | 「显示语言」／「应用界面显示语言」／「AI 回答语言」／「默认回答输出语言」／「可在这里切换@:general.srdName的回答语言」 |
| 界面语言项 | 「简体中文」「繁体中文」；`locales/zh.json`、`locales/en.json`（i18next，`package.json`） |

### 2.3 术语 / 专有名词

- 在 `web-strings.txt` 的 2266 条中**未检索到**「术语」「术语库」「专有名词」等文案（详见「证据缺口」）。因此**不认定存在**面向用户的术语表功能；**「推测」**：翻译质量控制仅体现为「翻译的效果不好」「翻译有误」等反馈入口。

### 2.4 标题优先

| 功能点 | 证据 |
| --- | --- |
| 标题优先翻译/显示 | 「翻译标题优先」／「优先显示翻译的标题」／「原标题优先」／「原題優先」／「翻訳タイトル優先」 |
| 标题显示顺序设置 | 「文章标题显示顺序」／「文献库文章标题优先显示顺序」／「文献库文章标题优先显示顺序」／「論文タイトル表示順序」 |

### 2.5 自动翻译开关（标题 / 速览 / 全文）

| 开关 | 证据 |
| --- | --- |
| 标题自动翻译 | 「开启后，自动翻译文献库文章标题」／「有効にすると、ライブラリの論文タイトルを自動翻訳」／「文章标题翻译」 |
| 速览自动翻译 | 「开启后，自动翻译文章速览」／「有効にすると論文速覧を自動翻訳」／「文章速览翻译」／「論文速覧翻訳」 |
| 全文自动翻译 | 「开启后，自动显示全文译文」／「有効にすると、全文の翻訳をデフォルトで表示」 |
| 翻译设置入口 | 「翻译设置」／「翻訳設定」／「内容设置」 |

### 2.6 额度与计费提示

| 功能点 | 证据 |
| --- | --- |
| 每日免费额度 | 「今日免费翻译额度已用完。」／「今日翻译额度已用完。」／「今日免费翻译字数已用完，请升级专业版」／「今日免费翻译额度已用完。🎁点此查看升级特惠，获取更多翻译额度。」 |
| 额度计量口径（字/天、页） | 「每天 AI 学术翻译 {count} 字」／「AI 翻译每天 {0} 字」／「AI 学术翻译提额至每天 10 万字」／「{quota} 字数*{count} 天」 |
| 用量展示与重置 | 「已使用 {used} / {limit} 字」／「已使用：{used} / {limit} 字，{time}重置」／「本次消耗 {used} 字」／「消耗 {count} 字」／「{time}重置」／「重置时间」／「今天额度已用尽。请等待 {time}额度重置。」 |
| 额度预警 | 「坚持阅读，收获满满！免费翻译额度剩余约30%」／「…剩余约20%」／「…剩余不足5%」／「额度即将用尽，可{0}继续使用。」 |
| 计费/套餐相关翻译文案 | 「{0}，享每日翻译{1}！」／「相当于每月全文翻译 200+ 普通论文，100+ 复杂论文。」 |

### 2.7 失败与重试文案

| 场景 | 证据 |
| --- | --- |
| 翻译失败 | 「翻译失败，请点击重试」／「翻訳に失敗しました。クリックして再試行してください。」／「翻译错误」（「翻訳エラー」） |
| 重试/重转入口 | 「点击重新翻译」／「重新翻译」／「保存&重转」／「保存 & 重转」／「重新生成」 |
| 翻译中状态 | 「翻译中...」／「正在翻译」／「已翻译」／「暂无翻译内容」 |
| 语言相同拦截 | 「检测到翻译语言与文章语言相同。」／「仍要翻译？」 |
| 服务端异常 | 「服务器繁忙，请稍后再试」／「网络错误，请检查网络连接后再试」 |
| 客户端 locale 兜底 | zh.json：`translation.failure.quota_depleted`「今日免费翻译额度已用完」、`translation.failure.some_problem`「遇到了一点点问题」、`translation.failure.miss_reading_id`「遇到了一点点问题：缺少reading id」 |
| 文章同步未完成时的翻译行为 | 「文章同步中，翻译将稍后开始。」 |

---

## 3. AI 能力

### 3.1 AI 问答 / AI 解答

| 功能点 | 证据 |
| --- | --- |
| 入口与命名 | 「AI 问答」／「AI 解答」／「AI 解释」／「问问 AI」／「问问@:general.srdName」／「读不懂、没头绪？直接问 AI」／「论文太难读？有问题，尽管问」 |
| 选中即问（划词解释） | 「论文太难读？选中任意内容，AI 帮你讲解」／「解释一下这段文本」／「请输入此 AI 解答内容的问题」／「请输入此 AI 问答内容的问题」 |
| 图表 / 公式 / 图片解释 | 「解释图表」／「解释一下这个公式」／「解释一下这张图片」／「复杂图表全解析」／「公式提取不乱码」／「公式」 |
| 全文开放式提问与跨篇问答 | 「支持对全文进行开放式提问，亦可划选文字、图表、公式进行智能解释，专业版更支持多达 20 篇文献的跨篇深度问答。」／「免费版支持 {freeCount} 篇问答。{upgrade}，开启 {proCount} 篇文献对比问答。」／「最多可选中 {count} 篇文献」／「用 Agent 研究已选论文」 |
| 参考上下文（结合文献库/项目文件） | 「@:general.srdName Agent 会结合项目文件和文献库回答，持续推进研究。」／「引用文献库论文/文件夹/项目文件」 |
| 回答长度与追问 | 「回答内容长度超出限制，如需继续生成请回复“继续”」／「继续针对这篇报告提问...」／「继续提问，或探索任何细节...」 |
| 免责声明 | 「内容由 AI 生成，仅供参考」／「由@:general.srdName生成」 |
| AI 回答语言/字号 | 「AI 回答语言」／「AI 问答字号」／「调整 AI 回复文本字号」 |

### 3.2 AI Agent（会话 / 技能 / 权限 / 工作区）

| 功能点 | 证据 |
| --- | --- |
| Agent 定位与入口 | 「AI Agent，您的研究助手」／「输入研究问题或任务，Agent 可以帮你找论文、定选题、整理文献库、设计实验。会话会自动保存，也可在其他设备继续。」／「请在@:general.srdName客户端使用 AI Agent」／「请在 @:general.srdName 客户端使用 AI Agent」 |
| 会话与项目管理 | 「新会话（不放入项目）」／「当前项目还没有会话」／「确定要清除会话记录吗？」／「清空会话」／「移动到项目」／「会话（上次使用：{date}）」／「其他设备的会话在这里」 |
| 项目工作区 | 「这是你的项目工作区」／「上传草稿、笔记、数据表、图片，或保存@:general.srdName Agent 生成的结果。PDF 文献请添加到文献库。」／「项目文件已导出到 {path}」／「当前客户端不支持打开工作区。」／「仅桌面客户端支持项目文件管理」 |
| 技能（Skills）体系 | 「技能」／「推荐技能」／「管理技能」／「已安装的技能」／「技能创建成功。」／「技能冲突」／「创建技能失败，请重试。」／「内置技能有可用更新，但本地文件已修改，请前往项目设置手动更新。」／「内置 - 已下架」／「内置 - 已修改」 |
| 权限规则（工具级授权） | 「权限管理」／「工具级：该工具总是允许」／「总是允许」／「允许一次」／「询问用户」／「保存された権限ルールはありません」／「确认清空当前项目的所有权限规则吗？」 |
| Agent 浏览器控制 | 「允许 Agent 使用浏览器访问网页」／「浏览器控制」／「Agent がブラウザでウェブページにアクセスすることを許可します」；工具清单（main.js）含 `navigate / snapshot / screenshot / click / type / scroll / press / back / exec_javascript / close_tabs / switch_tab / search_cn_scholar / read_cn_scholar_detail`；预加载脚本 `dist/preload_browser_agent.js`、`dist/preload_add_website.js`、`dist/public/agent.html` |
| Agent 可反问用户 | 「允许 Agent 向用户提问」／「询问用户」 |
| 并行与子任务 | 「并行工具调用」／「並列ツール呼び出し」／「子任务」 |
| 思考/推理可控 | 「模型」／「推理」／「推論レベル」／「开启思考」／「思考中」／「已深度思考（用时 { cost } 秒）」／「（用时 { cost } 秒）」／「已停止思考」 |
| Agent 页面类型识别 | main.js：`PAGE_TYPE_SEARCH_RESULTS / PAGE_TYPE_PAPER_DETAIL / PAGE_TYPE_PAPER_PREVIEW / PAGE_TYPE_ARTICLE_DETAIL / PAGE_TYPE_LOGIN / PAGE_TYPE_CAPTCHA / PAGE_TYPE_SCHOLAR_PROXY`（AI 判定页面类型后驱动浏览器任务）；`dist/public/crawl_verification_required_info.html`、`crawl_verification_required_control.html`（需人工处理验证码） |
| 任务中断提示 | 「当前有会话正在执行。离开此页面将中断会话，确定要离开吗？」／「当前有会话正在等待你处理。离开此页面将中断会话，确定要离开吗？」／「该会话当前已被其他连接占用。」 |

### 3.3 速览总结（AI 文献速览）

| 功能点 | 证据 |
| --- | --- |
| 速览模式 | 「速览」／「速览模式提供了 AI 文献速览、摘要和关键词等信息。帮助快速了解文献重点内容，决定是否进一步阅读。」／「支持文献速览。全文总结快人一步。」 |
| 速览内容项 | 「AI 论文速览」／「AI 文献速览」／「AI 文献重点速览」／「摘要」／「摘要片段」／「要点」／「核心概念速查」／「总结全文」 |
| 速览自动翻译 | 「开启后，自动翻译文章速览」 |
| 速览卡片动效开关 | 「文章卡片、速览封面图将会播放动画。若设备发热或卡顿，请关闭此功能。」／「动态效果」 |

### 3.4 综述报告（AI 综述 / 文献综述）

| 功能点 | 证据 |
| --- | --- |
| 产品化入口 | 「AI 综述报告」／「写综述报告」／「去写综述报告」／「长篇文章综述」／「综述报告示例」／「综述写作」 |
| 能力描述 | 「自动生成结构化文献综述，帮助快速梳理研究背景、核心观点、方法差异与关键结论。」；日文同义条目「構造化された文献レビューを自動生成し、研究背景、主要な見解、手法の違い、重要な結論をすばやく整理できます。」 |
| 输入与产出结构 | 「输入你的研究课题，快速生成文献综述或开题报告，例如：大语言模型在医学诊断领域的应用...」／「检索近 100+ 篇核心文献，生成一份本课题综述报告。」／「研究方法」／「研究目标」／「主要结论」／「创新点」／「暂未找到研究方法」／「暂未找到主要结论」／「暂未找到创新点」 |
| 耗时提示 | 「深度搜索中...（这个过程大约需要 10-15 分钟，在此期间你可以离开这个对话）」／「报告写作中...（这个过程大约需要 2-5 分钟，在此期间你可以离开这个对话）」／「计划制定中...（这个过程大约需要 1 分钟，在此期间你可以离开这个对话）」 |
| 效率宣传口径 | 「AI 深度检索了 {0} 篇文献，{1} 分钟完成手动阅读 {2} 小时的领域摸底。」 |
| 综述额度 | 「AI 综述报告额度」／「本月综述额度已用完」／「你本月的综述报告额度已全部使用完毕，额度将在下月自动重置。」／「开通专业版后，每月可获得 3 次综述报告额度。输入研究主题后，系统将帮助你检索相关文献并生成结构化综述内容。」／「写综述报告为专业版专享功能」 |
| 内测限制 | 「深度研究报告已生成（内测版暂不支持追问，如需发起新研究，请开始新会话）」 |
| 示例提示词 | 「【文献综述】帮我研究最近一年大语言模型在自适应任务规划中的主流技术路线，写一份文献综述。」／「【开题报告】深度调研 CRISPR-Cas9 基因编辑的脱靶效应，分析现有规避策略的局限性，写开题报告。」／「【研究现状】汇总社交媒体算法对青少年心理健康影响的最新进展，梳理其因果关系与神经机制。」 |

### 3.5 写作 / 引用 / 格式（含「润色」结论）

| 功能点 | 证据 |
| --- | --- |
| Word/WPS 写作插件 | 「Word / WPS 插件」／「写作插件为你{0}，{1}，并支持{2}。瞬间达标繁琐的学术规范。」／「微软 Word」／「Windows (Word 2013+)，macOS (Word 2016+) 及网页版」／「Word 写作插件目前仅上线内测版，添加官方企业微信获取资源，成为我们的内测用户。」／「坚果云AI写作@:accountPlan.pro」 |
| 参考文献引用助手 | 「参考文献引用助手」／「Word 参考文献引用助手」／「智能推荐参考文献」／「智能推荐引用文献，精准生成多种格式。」／「引用格式」／「引用形式」／「插入标准格式」／「导出引用」／「导出引用为实验性功能，请仔细核对内容准确性。」 |
| 论文格式检查 | 「免费检测论文格式」／「全篇格式检查」／「正文写完，还要被引文、格式折磨？」 |
| 润色 | 在 `web-strings.txt` 中**未出现**「润色」二字；**不认定**存在独立「润色」功能。**「推测」**：写作类能力以「写作插件 + 格式/引用」为主（上表），润色可能被归入写作插件能力描述 `写作插件为你{0}，{1}，并支持{2}` 的占位参数中（该句参数未在字符串层展开）。 |

### 3.6 AI 额度与商业化提示

| 功能点 | 证据 |
| --- | --- |
| AI Agent 额度 | 「AI Agent 额度」／「AI Agent 每月 {0} 额度」／「每月 {count} Agent 额度」／「AI Agent 额度包」／「购买 AI Agent 额度」／「AI Agent 额度不足时，可单独购买补充。」 |
| 「5 倍」营销口径 | 「{count} 倍 AI Agent 额度」／「立即获得 5 倍 AI Agent 额度，畅享高频阅读、写作与研究，并升级翻译、AI 问答、PDF 解析等权益。」／「{currentPlan}用户专享年付升级价，解锁 5 倍 Agent 额度与更强研究效率」 |
| 额度耗尽与重置 | 「本月 AI Agent 额度已用完」／「你本月的 AI Agent 额度已用完，额度将在下个月自动重置。可单独购买额度继续使用。」／「当前额度周期内额度已用尽，将于下月重置。」／「当前额度周期内额度已用尽，{0} 立即重置为 {1} 额度。」／「仅限 AI Agent 使用，未使用额度将在 {count} 天后随 AI Agent 额度重置清零。」 |
| 额度包换算口径 | 「适用于深度检索、文献分析、综述生成等 AI Agent 任务。每 {credits} 额度约可完成 {taskCount} 个复杂任务。」／「约 100-150 轮复杂任务」／「约 20-25 轮复杂任务」 |
| 各 AI 子额度 | 「AI 问答额度」／「AI 重排额度」／「AI 翻译额度」／「AI 综述报告额度」／「总额度」／「内测体验额度：剩余 {count} 次」 |
| AI 付费/升级提示位 | 「🚀 升级专业版，获取海量字数」／「升级后，AI Agent 额度立即提升，使用量将从 0 重新计算」／「升级不限次数」／「非专业版每天可试用 {0} 次，剩余 {1} 次。」 |

---

## 4. 文献管理与同步

### 4.1 文献库 / 文件夹 / 标签

| 功能点 | 证据 |
| --- | --- |
| 文献库 | 「文献库」／「文献」／「列出@:general.srdName文件夹」／「列出@:general.srdName文献」／「搜索@:general.srdName文献库」／「搜索文献库...」／「在文库找到 {count} 篇文章。」 |
| 文件夹增删改 | 「创建新文件夹」／「新建文件夹」／「添加新文件夹」／「修改文件夹」／「重命名文件夹失败，已存在同名文件夹。」／「确定要删除文件夹“{name}”吗？」／「文件夹名称过长。」／「请输入文件夹名称」 |
| 文献入夹/移出 | 「添加至文件夹：」／「未添加至文件夹」／「已添加至 {count} 个文件夹」／「从文件夹中移除」／「移动至文件夹」／「您确定要将 {count} 篇文献从所有文件夹中移除吗？」；出错文案「@:v__ReadingList...articles删除文件夹不会删除您的文章。所有子文件夹都将被删除。这个操作无法撤销。」 |
| 排序与筛选 | 「排序」／「排序方式」／「按名称」／「按添加时间」／「按修改日期」／「按阅读时间」／「名称 A-Z」／「名称 Z-A」／「从新到旧」／「从旧到新」／「最近修改在前」／「最近修改在后」／「筛选」／「输入关键词筛选」／「全部」／「无文件夹」／「未添加至文件夹」 |
| 空态/计数 | 「此文件夹下无文章」／「没有更多文章了」／「没有文章。 \| 共 1 篇文章。 \| 共 {count} 篇文章。」／「这个文件夹内包含 {count} 篇文章。」 |
| 标签 / Tag | 中文文案中未出现「标签」；但同一前端产物的检索文案引用了 tag 字段并做作者+标签联合检索：「@:v__SearchView.results._authors「{authors}」の著者およびタグ@:v__SearchView.results._tags「{tags}」を含む検索中です。」；代码侧阅读对象带 `tags`，同步时把 Zotero 分类写成 `zotero_category` 标签（main.js `getReadingTagList`、`insertOrReplaceReadingTag`） |

### 4.2 笔记与高亮

| 功能点 | 证据 |
| --- | --- |
| 笔记/高亮基础操作 | 「笔记」／「添加笔记」／「保存笔记」／「编辑笔记」／「删除笔记」／「查看笔记」／「添加高亮」／「取消高亮」／「删除高亮」／「高亮类型」／「高亮笔记」／「高亮与笔记」 |
| 空态 | 「无笔记，去文章里勾划吧～」／「无笔记内容」 |
| AI 自动高亮 | 「AI 划重点」／「重点高亮」／「自动高亮重点」／「启用 AI 重点高亮」／「AI 重点高亮已启用」／「AI 自动识别文章关键信息并智能高亮，让你阅读不再迷茫。」／「AI 已为您自动高亮文档中的核心内容（如研究目标、方法、结论和创新点）。点击侧边栏即可快速定位关键信息。首次加载高亮会稍慢一些，请耐心等待。」 |
| 笔记/高亮导出 | 「导出笔记（作为旁注）」／「导出高亮」／「导出双语重排 PDF」／「支持将重排后的双语全文导出为 PDF 格式，包含高亮与笔记，适合打印阅读。（仅支持电脑客户端）」；`preload.js` 的 `startExportPDF(readingId, layoutType, includeNotes, includeHighlight)`、`dist/public/export/prepare_print.js` |
| 限制提示 | 「该文章无法在译文中添加高亮或笔记。」／「该文章暂时无法添加高亮或笔记。」／「所选文本无法添加高亮或笔记。」／「所选文本过长。」／「文本过长。」 |
| 本地笔记事件表 | main.js：`notes_events`、`deleteAllReflowMeta()` 会清空 `notes_events` 与 `reflow_meta` |

### 4.3 阅读列表

| 功能点 | 证据 |
| --- | --- |
| 阅读列表 | 「阅读列表」／「我的阅读列表」／「查看阅读列表」／「回到阅读列表」／「搜索我的阅读列表」／「添加文献至你的阅读列表」／「添加该文章以便稍后阅读」／「已添加该文章」 |
| 未登录保护 | 「请先登录后保存文章到阅读列表」／「哎呀！请先登录再看全文。」 |

### 4.4 多端同步

| 功能点 | 证据 |
| --- | --- |
| 多端同步宣传 | 「多设备同步，阅读无界限」／「手机、平板、电脑实时同步」／「电脑、平板、手机，多设备数据同步、实时跟踪阅读进度、保存阅读数据。」／「下载手机、平板、电脑客户端，数据自动同步。随时随地阅读文献。」 |
| 同步过程与失败 | zh.json `sync.sync_reading_with_progress`「论文同步中，请勿关闭客户端。({{progress}}/{{total}})」、`sync.sync_note_with_progress`「笔记同步中，请勿关闭客户端。({{progress}}/{{total}})」、`sync.failure.retry_later`「数据同步失败，请稍后再试」、`sync.failure.network_error_retry_later`「数据同步失败，请检查网络连接后再试」；web：「论文同步失败，请稍后再试」「同步中，请稍后再试」「正在同步数据，请稍候」「已同步」 |
| 同步触发 | 托盘菜单「同步」（zh.json `tray.sync`）；代码 `syncManual`、`trySyncDatabaseQueueAsync`、`syncManual from_type=batch_size:10`（main.js） |
| 本地库 | `dist/native/better_sqlite3.node`（SQLite 本地库）、`localDB` 读写阅读/笔记/标签 |

### 4.5 导入 / 导出

| 功能点 | 证据 |
| --- | --- |
| 导入入口与进度 | 「导入」／「导入论文」／「导入文章」／「导入文件」／「导入进度」／「正在导入 ({progress}/{total})」／「导入完成」／「导入未完全完成」／「导入被中止」／「已跳过 {count} 个重复文件。」／「已跳过 {count} 个不支持解析的文件。」／「已存在重复文档」／「没有可导入的文件。」 |
| 拖拽导入 | 「拖拽论文到此窗口即可阅读，或点击按钮导入」／「将您的文件拖放到这里或{0}」／「点击这里，上传文献」 |
| 上传限制 | 「单次最多 @:v__SavePaperView.uploadFile.files，每个文件最大 {size}。仅支持 {type} 文件。」／「抱歉，您的每日上传文件已达上限（{count} 个），请明天再试。」／「抱歉，您的文件大小超出了 {size}/个。」／「文件大小超出 {size}」／「单篇文献上传大小」／「支持上传更大体积的单篇文献。」 |
| 导出 | 「导出」／「导出为 PDF」／「导出双语重排 PDF」／「导出项目」／「导出设置」／「导出中... {percent}%」／「导出项目文件失败，请重试。」／「当前客户端不支持导出项目文件。」／「请等待前一个文档导出完成」 |
| 批量结果回执 | 「{success} 篇保存成功，{fail} 篇保存失败。」／「{success} 篇删除成功，{fail} 篇删除失败。」 |
| 通过 URL 添加 | 「粘贴 URL 链接来添加」／「粘贴学术文献的 URL 链接」／main.js `importPdfFromUrl` |

### 4.6 Zotero 集成

| 功能点 | 证据 |
| --- | --- |
| 集成定位 | 「Zotero 集成」／「Zotero 阅读助手」／「Zotero 文献一键导入」／「一键导入 @:general.brandName.zotero 中的文章，使用 @:general.srdName 阅读」 |
| 导入流程 | 「从 Zotero 导入」／「从 Zotero 导入文章」／「@:general.brandName.zotero 导入配置成功！」／「@:general.brandName.zotero 轻松导入」／「一键导入完成」／「你的 Zotero 库看起来空空的」／「已选 {selectedCount} 个文件夹，待导入 {selectedFileCount} 篇」 |
| 访问令牌（本地读取，不上传） | 「本地读取：仅访问 Zotero 本地索引，数据不经过第三方。」／「Scholaread 将读取本地 Zotero 数据库」／「目前您无法创建新密钥，请{0}以导入 Zotero 中的文章。您可随时撤销不再使用的密钥。」／「全部密钥」／「尚无密钥」／「确定要撤销密钥吗？」／「使用此密钥的应用程序将无法再访问您的账户。」 |
| 双向打开 | 「使用 @:general.srdName 打开 Zotero 文章」／「使用 Scholaread 打开 Zotero 中的文献，可在设置中关闭。」／「@:general.srdName で Zotero 文献を開く」 |
| 插件下载 | 「下载 @:general.brandName.zotero {version} 插件」／「通过插件自动将 @:general.brandName.zotero 中的文献导入 @:general.srdName 阅读。」／「安装并覆盖」／「无感迁移：支持文件夹级导入，无需手动整理。」 |
| 分类映射与未分类 | zh.json `zotero.uncategorized_items`「未分类条目」；代码侧 Zotero 集合以 `zotero_category` 写入标签，EPUB 附件走 `pc_zotero_file_is_epub` 埋点 |
| 同步控制 | `preload.js`：`loadZoteroCollections`、`startSyncZotero`、`getZoteroSyncState`、`retrySyncZotero`、`switchZoteroSyncState`（暂停/继续）、`checkZoteroOpenWithScholaread` |

### 4.7 CAJ / EPUB / PDF 导入

| 功能点 | 证据 |
| --- | --- |
| CAJ 导入 | zh.json `file_import.parsing_caj`「正在解析CAJ文件，请稍后」、`file_import.failure.require_login`「导入失败，请先登录后再尝试导入CAJ文件」、`file_import.failure.caj_import_failure`「很抱歉，CAJ文件导入失败」；`service.js` 的 `caj2pdf` 上传转换接口、MIME `application/vnd.cnki.caj` |
| EPUB 支持 | 图标资源 `dist/public/icon_epub.png`；`service.js` 依赖 `epub@1.2.1` 解析 EPUB（`loadReadingForEpub`、`buildCatalogueForEpub`、`getEpubRes`、`/epub_res/` 资源代理）；`main.js` MIME 常量含 `EPUB:"application/epub+zip"` |
| PDF | 图标 `dist/public/icon_pdf.png`；`pdf2htmlEX.wasm`（`dist/wasm/`）做 PDF→HTML 重排转换；`dist/public/pdf_detect.html` + `preload_pdf_detect.js`（检测到 PDF 时弹窗） |
| 格式限制 | 「不支持的文件格式」／「不支持的文件类型」／「非 PDF 格式」／「仅支持同步 PDF 文件」／「抱歉，您的部分文件是不受支持的格式。」／「当前文件类型暂不支持预览」 |
| Windows 文件关联 | `main.js` 打包配置 `fileAssociations: [{ext:"pdf", role:"Editor"}, {ext:"caj", role:"Editor"}]` |

### 4.8 分享与协作

| 功能点 | 证据 |
| --- | --- |
| 分享入口 | 「分享」／「保存二维码」／「扫码打开」／「扫描二维码，安装到手机」／「从社交媒体转发」 |
| 分享页/分享阅读 | 「在{0}中继续」／「查看 {count} 篇论文」／「复制原文」／「打开链接」／「在新窗口打开」；代码侧 `getReadingsByShareIds`、`share_id`、`is_open_access`（service.js `buildSharesResponse`） |
| 举报/内容合规 | 「举报」／「举报说明：」／「抱歉，由于受到版权保护，无法查看该文章。」／「抱歉，由于受到版权保护，无法查看该信息。」 |
| 团队/协作 | **未发现**面向用户的「协作」「共享文件夹」「团队成员」文案；**「推测」**：分享是单篇/读列表级别的对外分享，非多人协同编辑 |

---

## 5. 检索与发现

### 5.1 检索入口

| 功能点 | 证据 |
| --- | --- |
| 全网/期刊检索 | 「全网搜索」／「文献检索」／「搜索全网文献，导入@:general.srdName阅读」／「在期刊网站搜索」／「按 / 可在期刊网站搜索」／「搜索」 |
| 站点式检索（内置多标签浏览器） | `dist/tab-container/`（阅读标签页 + 站点导入标签页）、`dist/public/search.html`、`dist/preload_search.js`、`dist/preload_add_website.js`、`dist/public/add_website.html`；tab-container/index.html：左侧 `#channel-list` 频道列表 + 「添加搜索引擎」，右键「删除」 |
| 示例频道 | `tab-container/index.html` 中保留注释 `<!-- <div class="channel">知网</div>-->`（示例频道，被注释） |
| 检索结果保存 | 「一键导入」／「保存至@:general.srdName」／「保存至 @:general.srdName」／「搜索结果」／「结果（{count}）」／「，在列表中找到 {count} 个结果」 |
| 全文获取失败兜底 | 「努力获取全文...」／「需前往原网页获取」／「无法获取下载链接，请稍后再试。」／「有全文」／「全文状态」／「抱歉，找不到文章。」／「当前内容无法展示，请尝试搜索其他内容。」 |
| 智能检索建议 | 「大家都在搜」／「试试搜索这些…」／「试试输入标题，作者或摘要进行搜索...」／「想找什么论文？例如“近三年 RAG 的综述论文”」 |

### 5.2 支持的站点（规则文件证据）

| 来源 | 证据 |
| --- | --- |
| 元数据/详情抽取站点 | `extract_paper_detail_rule.json` 覆盖 arXiv、ScienceDirect、PubMed、Springer、**kns.cnki.net（知网）**、pubscholar、Frontiers、ASM、Nature、BMC、AHA、ACS、ACM、IOP、Cell、APS、IEEE、MDPI、SIAM、Wiley 系列、Copernicus、PMLR、CVF、AEA、NeurIPS、Science、BMJ、EMBO、JCI、SAGE、PNAS、PMC、PeerJ、OUP、ASCO、eLife、A&A、**cqvip（维普）**、**d.wanfangdata.com.cn（万方）** 等约 60 条 |
| 检索结果页抽取站点 | `extract_paper_search_result_rule.json`：arXiv、Springer、Google Scholar、CNKI、维普、万方 |
| 页面类型识别 | `page_detect_rule.json`：arxiv / cnki / sciencedirect / pubmed / iopscience / springer / semanticscholar / scholar.google.com / cqvip / wanfangdata 等 20+ 条 |
| 主进程访问过的学术域名 | `scan-main.txt`「URL-ish hosts」：`arxiv.org`、`kns.cnki.net`、`www.cnki.net`、`www.wanfangdata.com.cn`、`d.wanfangdata.com.cn`、`s.wanfangdata.com.cn`、`www.cqvip.com`、`scholar.google.com`、`www.semanticscholar.org`、`www.sciencedirect.com`、`ieeexplore.ieee.org`、`www.nature.com`、`www.webofknowledge.com`、`xueshu.baidu.com`、`www.connectedpapers.com`、`researchrabbitapp.com`、`api.crossref.org`、`www.sci-hub.se` 等 |
| Agent 专属知网工具 | `main.js`：`TOOL_SEARCH_CN_SCHOLAR:"search_cn_scholar"`、`TOOL_READ_CN_SCHOLAR_DETAIL:"read_cn_scholar_detail"` |
| 全文下载渠道（代码级） | `main.js`：`config_scholar_proxy_url` + `config_allow_download_from_proxy`（Google Scholar 代理式获取）、`config_allow_download_from_sci_hub` + `sci-hub://` 协议处理（`www.sci-hub.se`）——**代码证据，非用户文案**；对应的界面提示为「@{...} 仅提供文献检索和导入途径，期刊网站使用权限以用户具体订阅情况为准。」 |
| 浏览器扩展 / 书签工具 | 「{browser} 插件」／「谷歌浏览器 (Chrome)」／「火狐浏览器 (Firefox)」／「微软浏览器 (Edge)」／「安装@:general.browserExt或@:general.bookmarklet」／「@:general.browserExtまたは@:general.bookmarkletを使用」／「使用小书签」／「第一步：将@:general.srdName添加至你的书签栏」／「第二步：点击一下，保存论文」／「将这个按钮拖拽至你的书签栏」／「账号不匹配。请创建一个新的小书签吧。」／「获取小书签，请复制这个页面到电脑浏览器。」 |
| PDF 探测与「打开方式」 | 「Scholaread检测到PDF文件」（zh.json `monitorFileDownload.notificationBody`）、「立即打开 {{name}}」（`monitorFileDownload.notificationTitle`）、`dist/public/pdf_detect.html`、`preload_pdf_detect.js`、`regardPDFAsPaper`（把下载到的 PDF 当论文处理） |

---

## 6. 账号、商业化与合作

### 6.1 登录方式

| 功能点 | 证据 |
| --- | --- |
| 登录入口 | 「登录」／「登录方式」／「使用以下方式登录@:general.srdName」／「快速登录」／「登录已有账号」／「登录网页版」／「重新登录」／「请登录后继续」 |
| 手机号 | 「手机号」／「绑定手机号」／「更换手机号」／「電話番号を変更」 |
| 第三方账号绑定 | 「绑定{brand}」／「{brand}已绑定」／「绑定成功！您可以使用“{brand}”登录 @:general.srdName。」／「绑定失败，您无法绑定已经注册过@:general.srdName的“{brand}”账号。」／「取消绑定」／「确定要取消绑定吗？」／「在浏览器中绑定{brand}」／「第三方平台」 |
| 具体品牌（i18n key 证据） | web 文案中出现 `@:general.brandName.alipay`（「打开@:general.brandName.alipay扫一扫」）、`@:general.brandName.wechat`（「请使用@:general.brandName.wechat扫描二维码…」）、`@:general.brandName.apple`（「您已通过 @:general.brandName.apple 订阅…」）、`@:general.brandName.stripe`（「绑定 @:general.brandName.stripe 自动续费」）、`@:general.brandName.nutstore`（坚果云：「绑定@:general.brandName.nutstore账号」「@:general.brandName.nutstoreを訪れる」）、`@:general.brandName.zotero` |
| 淘宝 / 书城登录（调试入口） | `main.js` 菜单：`t.push({label:"登录淘宝", click:…"login_taobao"})`，`showTaoBaoLogin` 打开 `http://www.booktsg.com`，窗口类型 `TYPE_LOGIN_TAO_BAO`；**「推测」**：该入口出现在 `demo` 条件分支内，属调试/合作渠道入口，非标准用户路径 |
| 设备与账号安全 | 「您的账号已在多台同类型设备上登录。当前设备登录状态已失效。@:general.srdName账号仅限个人使用，请避免账号共享以确保访问稳定。」／「经系统检测，您的账号近期在多个设备和地点频繁登录。存在异常违规共享行为，我们已暂时对您的账号实施了封号措施。」 |
| 登录态失效 | 「登录状态已失效」／「登录失败，请稍后重新登录」／`dist/public/login_failure.html` |

### 6.2 会员 / 版本 / 权益

| 功能点 | 证据 |
| --- | --- |
| 版本档位 | 「免费版」／「免费体验版」／「Free 版」／「专业版」／「Pro 版」／「专业版 Max」／「Max 版」／「会员计划」／「套餐权益对比」 |
| 计费周期 | 「按月付费」／「月付」／「季付」／「年付」／「年付@:accountPlan.pro」／「月付@:accountPlan.proMax」／「{0}{1}/年」「{0}{1}/月」「{0}{1}/季」「{0}{1}/天」 |
| 权益描述 | 「为什么选择@:general.srdName？」／「为什么选择@:general.srdName@:accountPlan.pro？」／「海量 AI 重排引擎额度，可以处理 95% 的复杂文档内容，例如图像、复杂表格、LaTeX 公式等。」／「适合日常文献阅读、翻译、提问」／「适合高频文献阅读、写作、研究」／「日常阅读、翻译、提问」／「适合继续进行深度检索、文献分析、综述生成等 Agent 任务」 |
| 升降级限制 | 「当前为@:accountPlan.proMax，暂不支持降级购买@:accountPlan.pro」／「@:accountPlan.pro暂不支持升级{plan}，可选择@:v__PriceViewNew.plans.pro.proMaxAnnually 抵扣剩余价值」／「暂不支持降级」／「暂不支持升级」／「原价 {originalPrice}。已抵扣{plan}剩余天数价数值：-{deductedPrice}」 |
| 试用/次数限制 | 「非专业版每天可试用 {0} 次，剩余 {1} 次。」／「免费体验次数已用完，请升级专业版」／「开通后每月可获得 {count} 次」／「不限额度」／「无限次数」／「无限字数」 |
| 到期/续费 | 「到期时间：{date}（{days}）」／「有效期自支付成功日起重新计算 1 年」／「订阅期间随时取消」／「下一个计费日期前，允许随时取消会员订阅。」／「管理订阅」／「支持7天无理由退款」 |

### 6.3 支付

| 功能点 | 证据 |
| --- | --- |
| 支付渠道文案 | 「支持：{0} @:general.brandName.alipay / {1} @:general.brandName.wechat」／「打开@:general.brandName.alipay扫一扫」／「支付完成后…」（「支付后将立即升级为{plan}」） |
| Stripe / Apple 订阅管理 | 「您已通过 @:general.brandName.stripe 订阅，请通过 @:general.brandName.stripe 完成支付或管理订阅。」／「绑定 @:general.brandName.stripe 自动续费」／「无法跳转到 @:general.brandName.stripe 的订阅页面，请稍后重试。」／「正在跳转到 @:general.brandName.stripe」 |
| 坚果云联售 | 「坚果云联售购买常见问题」／「坚果云AI写作@:accountPlan.pro」／「怡氧@:accountPlan.pro」／「感谢您的支持！购买此联售套餐前，需绑定@:general.brandName.nutstore账号作为可选登录方式，并使用@:general.brandName.alipay支付。请点击下方按钮，打开设置页面进行绑定。」 |
| 联想（Lenovo）合作 | `preload.js`：`isLenovoCooperation()`、`getPaymentLenovo(plan, mode, qrcodeSize, lang, couponCode)`、`getPaymentLenovoV2`；`main.js`：`isLenovoCooperationEnable = ()=>"win32"===process.platform && "Lenovo"===getChannelName()`、`registerLenovoPaymentHandler`、`getLenovoTradeInfo`、`bindLenovoCallBack`、`lenovoSdkService`（`Lenovo SDK is only supported on Windows.`，动态加载 `extensions/LYSDK2.dll`）；`dist/native/extensions/LYSDK2.dll`、`LsfSdk.dll`、`ludp.dll` |
| 支付结果与失败 | 「您已成功支付」／「支付失败」／「已取消支付」／「支付遇到问题？点我」／「我已完成支付，刷新状态」／「获取支付结果失败，请稍后再试。」／「很抱歉，暂时无法获取购买链接，请返回重新点击购买。」／「暂时无法购买，请联系客服处理」 |
| 发票 | 「申请发票」／「申请已提交，感谢使用！」／「請求書を申請」 |

### 6.4 邀请 / 优惠券 / 抽奖

| 功能点 | 证据 |
| --- | --- |
| 优惠券 | 「优惠券」／「{coupon} 元优惠券（{count} 天有效期）」／「新用户限时优惠券」／「老用户限时优惠券」／「您有优惠券即将到期」／「{0} 优惠即将到期 {1}」／「优惠券无效，请刷新此页面后重试」／「暂无可用的优惠券」 |
| 立减/折扣 | 「恭喜获得 {number} 无门槛立减」／「恭喜获得最高 {number} 老用户立减回馈」／「年付立减 {0}」／「限时特惠 年付立减 {0}」／「省 {text}」／「最高省 {text}」／「折扣」／「最划算」／「不划算」 |
| 优惠倒计时/入口 | 「优惠锁定倒计时：{0}」／「点我更优惠」／「{currentPlan}用户专享年付升级价…」／「立即领取」 |
| 邀请好友 | 中文条目未出现「邀请」；同包日文条目给出该能力：「友達を招待」／「招待コードをお持ちですか？」／「あなたも友達もそれぞれ {count} Agent クレジットを獲得」／「入力すると {count} Agent クレジットを獲得」→ 邀请码机制、双方各得 Agent 额度 |
| 抽奖/礼包 | 「🎉 恭喜获得神秘礼包！」／「打开礼包」／「🎊 抽中 {count} 翻译字数！」／「🎊 抽中 {count} 天专业版会员！」／「🎊 抽中 {coupon} 元优惠券！」／「有几率抽取：」／「很遗憾！没抽中礼品」／「您已领取过礼品了！快去阅读吧」／「活动名额已满。」／「活动尚未开始。」／「活动已结束。」／「您已经参加过该活动，请勿重复参加。」 |
| 下载客户端奖励 | 「下载电脑客户端奖励：{0}」／「系统将为您发放 @:general.srdName 专业版相关权益」 |

### 6.5 广告位

| 功能点 | 证据 |
| --- | --- |
| 购买广告位开关 | `main.js`/`preload.js`：IPC `checkShowPurchaseAdsEntry`，`handleCheckShowPurchaseAdsEntry` 目前直接 `resolve(true)`（即默认展示购买入口） |
| 「无广告」作为付费卖点 | 「无广告沉浸阅读」／「无广告界面，专注阅读。」／「{0}（无广告，更流畅的 Office 套件）」（坚果云 Office 联售权益） |
| 站内推广位 | 「本周综述报告精选」／「综述报告示例」／「想针对你的课题生成这样一份综述报告吗」／「想写综述没头绪，又怕 AI 瞎编文献？」／「不感兴趣」／「暂无可用的推荐内容。」 |

### 6.6 企业版 / 机构版 / 客户支持

| 功能点 | 证据 |
| --- | --- |
| 客服与支持 | 「联系客服」／「联系我们」／「联系专业版客户支持」／「VIP 客户支持」／「VIP 快速通道，咨询解决问题快人一步。」／「如有疑问，请联系官方客服。」／「请使用@:general.brandName.wechat扫描二维码，添加{account}为好友，即可获得专业版专属客户支持。」 |
| 团队版线索 | 「您绑定的@:general.brandName.nutstore账号可能已是团队版，或处于冻结/禁用等异常状态，无法完成升级。请登录@:general.brandName.nutstore官网查看详情。」 |
| 企业/机构版 | **未发现**独立的「企业版」「机构版」「学校版」文案；**「推测」**：机构/团队场景通过坚果云团队版联售与「联系专业版客户支持」承载 |
| 合规与主体 | 「沪ICP备2021026665号-2」／「沪公网安备31011502400586号」／「网信算备310112174995401260029号」／「{year} 上海亦答网络科技有限公司 保留所有权利。」／「{year} Astronet Technology PTE LTD 保留所有权利。」（国际主体）／「返回国际版」／「为给您提供更快速、稳定的服务，我们已为您自动切换到国内站。」 |

---

## 7. 客户端与体验细节

### 7.1 托盘

| 功能点 | 证据 |
| --- | --- |
| 托盘菜单项 | zh.json `tray.home`「显示主界面」、`tray.sync`「同步」、`tray.quit`「退出」、`tray.tips`「靠岸学术」；`main.js` `createTray` / `closeTray` / `buildFromTemplate([tray.home, tray.sync, tray.quit])`、事件 `tray_show_home` / `tray_sync` |
| 最小化到托盘 | `main.js`：窗口 hide 后 `createTray()`；退出时 `closeTray()` |

### 7.2 桌面宠物

| 功能点 | 证据 |
| --- | --- |
| 桌面宠物开关与状态 | 「桌面宠物」（web）；`preload.js`：`showDesktopPet`、`getPetEnabled`、`setPetEnabled`；`main.js`：`initializePet`、`showPet`、`setAppForeground`/`setAppVisible`、`setPresentationEnabled` |
| 动画状态机 | `dist/public/pet-assets/animation-manifest.json` + `frames/` 六组动画：`greet`、`idle`、`reading`、`sleep`、`agent-work`、`agent-input`、`agent-success`（每组 frame-01…06） |
| 气泡与交互 | `dist/public/pet-assets/bubble-component/pet-bubble.js`/`.css`、`dist/public/pet.html`、`dist/preload_pet.js`（`pet:update`、`pet:activate`、`pet:notification-activate`、拖拽 `pet:drag-start/move/end`、右键菜单 `pet:context-menu`、通知关闭 `pet:notification-dismiss`） |
| 与 Agent 状态联动 | `preload.js` 注释给出业务事件：`{business:"agent", eventType:"run_active" | "run_succeeded" | "user_action_required" | "user_action_handled" | "run_failed" | "run_canceled" | …}` 与 `{business:"reading", active}` |

### 7.3 快捷键

| 功能点 | 证据 |
| --- | --- |
| 应用内查找 | `main.js`：`globalShortcut.register("CommandOrControl+F", …)` 打开 `public/search.html` 的查找视图（`find-in-page`），窗口失焦时 `unregister` |
| 关闭查找 | `main.js`：`globalShortcut.register("Esc", ()=> ipcMain.emit("closeSearch"))` |
| 其他 | 未发现用户可自定义快捷键的设置文案或 `globalShortcut` 注册表；**「推测」**：快捷键仅上述内置两项（另见 `menu.edit` 的标准编辑快捷键：撤销/剪切/复制/粘贴/全选，zh.json `menu.edit`） |

### 7.4 更新

| 功能点 | 证据 |
| --- | --- |
| 版本检查/升级 | `preload.js`：`checkNewVersion`、`applyHotUpdate`、`upgradeNewVersion(url)`；`main.js` IPC `checkNewVersion`、`applyHotUpdate`、`upgradeNewVersion`；依赖 `electron-updater@6.1.7`（`package.json`） |
| 文案 | 「发现新版本」／「发现新版本 {version}」／「安装新版本」／「安装新版本将覆盖当前修改。」／「当前版本 {version}，建议更新到最新版本」／「最新版本：{0}」／「新版本更新内容：」／「自动更新失败」／「立即更新」／「今すぐ更新」 |
| 能力门槛校验 | 「当前客户端版本不支持修改数量，请升级到 {version} 及以上版本」／「请升级客户端后重试（不支持 {capability}）」／「当前桌面客户端版本过低。请重启或升级后再试。」／「当前桌面客户端暂不支持该功能。」 |

### 7.5 网络检测 / 代理

| 功能点 | 证据 |
| --- | --- |
| 网络检测工具 | zh.json `menu.net_detect`「网络检测」；`dist/public/net_detect.html`；`main.js`：`showNetWorkDetectDialog`、`showNetworkAnalysisTools`、`detectNetworkResult` |
| 网络文案 | 「网络诊断」／「网络错误，请检查网络连接后再试」／「连接中」／「已连接」／「未连接」／「正在恢复连接」／「再接続中」／「WebSocket 连接失败。」／「WebSocket 握手超时（readyState: {readyState}）。」／「该会话当前已被其他连接占用。」 |
| 代理支持 | `package.json` 依赖 `hpagent`、`http-proxy-agent`、`socks-proxy-agent`、`proxy-from-env`；`main.js`：`configureProxy`（模块 72816 尾部 `e.exports={configureProxy:h}`） |
| 国内/国际站 | 「为给您提供更快速、稳定的服务，我们已为您自动切换到国内站。」／「返回国际版」 |

### 7.6 日志导出

| 功能点 | 证据 |
| --- | --- |
| 日志导出菜单 | zh.json `menu.logs`「打包日志」、`package_logs.export_logs`「日志文件导出」、`package_logs.save`「保存」；`preload.js`：`exportLog(info)`、`main.js` IPC `exportLog` |
| 日志框架与目录 | `package.json`：`winston@3.11.0`、`winston-daily-rotate-file@4.7.1`、`file-stream-rotator`；`main.js` 配置键含 `agentLogDir:"agent_log_dir"` |
| Agent 调试日志 | `preload.js`：`projectAppendDebugLog(studyId, content, sessionId)` |
| 错误上报入口 | 「报告错误」／「错误类型：」／「正在上报」／「上传截图以便开发人员快速修复」／「请分享您遇到的问题...」／「请简单描述问题...」／「补充说明（选填）：」／「举报说明：」 |

### 7.7 缓存管理

| 功能点 | 证据 |
| --- | --- |
| 缓存信息与清理 | 「缓存大小」／「缓存目录」／「清除缓存」／「确定要清理缓存吗？」／「清理成功」／「清理失败」／「清理」；`preload.js`：`getCacheInfo`、`clearCache`、`setCachePath`；`main.js` IPC `getCacheInfo`、`setCachePath`、`clearCache`、`migrateLocalCache`、`registerDiskCacheHandler` |
| 清理副作用提示 | 「为了避免清理缓存过程中数据状态异常，在清理的过程中会先关闭所有阅读标签页」／「キャッシュ削除中のデータ状態異常を防ぐため、削除開始前にすべての閲覧タブを閉じます。」 |
| 缓存目录类型 | `main.js`：`CACHE_DIR_TYPES={PDF:"pdf", REFLOW:"reflow"}`、`getLocalExternalCacheDir()`、`internal_cache_dir`/`cache_dir` |
| 磁盘空间 | `package.json` `check-disk-space`；`dist/public/disk_space_exhaust.html`、`dist/preload_disk_space_exhaust.js`、IPC `closeDiskSpaceExhaustDialog`、`autoCheckDiskSpace`（main.js） |
| 路径异常 | 「文件夹可能暂时离线、被占用或所在磁盘不可用，请稍后重试。」／「请在系统设置中允许 Scholaread 访问该文件夹，或重新选择有权限的目录。」 |

### 7.8 帮助中心与引导

| 功能点 | 证据 |
| --- | --- |
| 帮助入口 | zh.json `menu.help`「帮助中心」、`menu.about`「关于」、`menu.official_site`「访问官网」、`menu.sync`「同步」、`menu.exit`「退出」、`menu.developer_tools`「切换开发者工具」；`dist/public/about.html` |
| 帮助/教程/手册 | 「帮助」／「帮助中心」／「查看教程」／「使用手册」／「使用指引」／「翻译功能常见问题」／「影印版 PDF 相关问答（「什么是影印版？」「通常文書との違いは？」）」／「坚果云联售购买常见问题」／「查看旧版学术 AI 记录」 |
| 新手引导 | 「快速开始」／「开始使用」／「完成入门教程」／「恭喜你，完成快速开始！」／「通过完成以下任务，进一步了解@:general.srdName的功能。」／「描述你的研究方向、课题或具体问题，我们以此来建议适合你的启动任务。」／`main.js`：`showUserGuide`、`enableShowUserGuide`、`shouldShowAssociateGuide`（文件关联引导）、`/public/install/background/mac_dmg_bg1_zh.png`（安装引导图） |
| 引导式任务卡 | 「打开并阅读一篇学术文献」／「上传论文，或从 Zotero 导入，开始阅读。」／「导入一篇文章试试？」／「第一次读文献，应该从哪开始？」／「你想从哪里开始？」／「我有论文」／「我有一个研究主题」 |
| 弹窗/浮层 | 「显示弹窗」／「悬浮窗」／「别ウィンドウで開いています」／「查看更多设置」／「显示全部方式」 |
| 多标签容器 | `dist/tab-container/`：`container/container.js`、`pages.js`、`window.js`、`agent-tab-ownership.js`、`assets/agent_tab_cursor-*.svg`（Agent 操作标签页高亮边框 `.agent-tab-frame`） |

---

## 8. 数据与隐私相关文案（归类，不复述任何密钥）

| 类别 | 证据 |
| --- | --- |
| 账号注销 | 「注销账号」／「申请注销」／「确定要删除吗：」／「删除后不可恢复，是否继续？」／「您的账号 {account} 已注销，感谢您过往对@:general.srdName的支持，我们会不断改进产品与服务，期待与您再会！」；`main.js` IPC `onDeleteAccountCompleted`；日文「アカウント削除」「アカウントを削除」 |
| 协议与政策 | 「隐私政策」／「用户协议」／「使用协议」／「购买协议」／「《购买协议》」／「协议」／「支付即表示您同意并接受@:general.srdName{0}」／「私は{0}と{1}を読んで同意しました」 |
| 崩溃/错误上报 | `package.json` 依赖 `@sentry/electron@1.5.2`（含 `@sentry/node`、`@sentry/browser`、`@sentry/core` 等）；`main.js` 中 `initSentry()` 调用 `Sentry.init({ dsn: <指向 sentry-backend.jianguoyun.com 的上报端点>, beforeSend(...) })`，`beforeSend` 内置过滤逻辑（对特定 message / logentry 决定是否上报）；上报入口文案「报告错误」「正在上报」 |
| 埋点与行为统计 | `preload.js` `reportEvent(eventName, params)`；`main.js` IPC `reportEvent`；事件名常量示例 `pc_signin_success`、`pc_signup_success`、`pc_zotero_file_sum`、`pc_zotero_import_success`、`pc_zotero_import_fail`、`pc_zotero_not_install`、`pc_zotero_open_file`、`pc_zotero_plugin`、`report_zotero_installed_date`；`tab-container/index.html` 埋点 `pc_search_host_click`；崩溃/导出进度等 UI 事件 `getCapture`、`onExportProgress` |
| 设备信息 | `package.json` 依赖 `node-machine-id@1.1.12`；`main.js` `machineIdSync`（Win 读注册表 MachineGuid、macOS ioreg、Linux machine-id）生成设备指纹并写入 `global.userDeviceId`；IPC `getServerDeviceId`、`getUserAgent`、`getClientInfo`；配置键 `screen_size`、`host` |
| 账号共享风控 | 「您的账号已在多台同类型设备上登录。当前设备登录状态已失效。@:general.srdName 账号仅限个人使用，请避免账号共享以确保访问稳定。」／「经系统检测，您的账号近期在多个设备和地点频繁登录。存在异常违规共享行为，我们已暂时对您的账号实施了封号措施。」 |
| 本地数据与「数据不出本地」承诺 | 「本地读取：仅访问 Zotero 本地索引，数据不经过第三方。」／「安全保障：我们不会修改、移动或删除你的任何原始文献。」；本地 SQLite（`better_sqlite3.node`）+ 缓存目录，缓存清理需用户确认 |
| 第三方 AI / 云服务线索 | `main.js` 中出现 `https://ai-assistant.jianguoyun.net.cn/openid/openrouter/v1/chat/completions`（坚果云 AI 助手 / OpenRouter 转发，含模型名 `google/gemini-3.1-flash-lite` 与 apiKey 兜底逻辑）；`waitForVolcengineSdkLoad`（`window.reportVolcengine?.sdkLoad`）表明页面内嵌火山引擎 SDK；`sentry-backend.jianguoyun.com` 为上报后端 |
| 网络暴露面（旁证） | `scan-main.txt` 主机清单含 `api.scholaread.cn`、`api-demo.scholaread.cn`、`cdn.scholaread.com`、`pdf2html.com`、`ai-assistant.jianguoyun.net.cn`、`sentry-backend.jianguoyun.com`、`api.keygen.sh`（授权/许可证校验）、`github.com`/`raw.githubusercontent.com`（热更新或技能下发）、`s3.amazonaws.com`、`workspace-export.invalid`（占位域名） |
| 数据导入导出与迁移 | 「导出项目」／「导入项目」／「项目迁移」／「合并所选文件并保留本地独有内容；如有冲突，由你选择保留版本。」／「使用所选文件中的内容替换当前项目，本地原有内容将不再保留。」／「将会删除项目内的所有文件、会话、技能等。该操作无法恢复。你可以{0}或{1}。」；`preload.js` 工作区 zip 导入导出系列 API |
| 危险操作区 | 「危险操作」／「危険操作エリア」／「删除后不可恢复，是否继续？」／「确认删除」／「清空权限规则失败。」 |

---

## 证据缺口

以下项在本次可用证据中**没有找到用户可见文案或代码实现**，或证据不足以支撑结论，需要在后续分析（如抓取 web 包本体、运行客户端、抓取真实接口）中补证：

1. **术语库 / 专有名词表**：`web-strings.txt` 中无「术语」「专有名词」「术语表」条目；`main.js`/`service.js` 中也未见术语词典相关逻辑。倾向结论：**不存在**（而非仅缺文案）。
2. **润色**：无「润色」文案；写作能力只能由「写作插件为你{0}，{1}，并支持{2}」「Word / WPS 插件」间接推断，且参数未展开。需看 web 包本体或其 i18n 资源才能确认子能力清单。
3. **双栏阅读开关**：仅见「改良传统两栏格式排版」（把原始双栏 PDF 重排），未发现用户可切换的分栏显示设置。
4. **行距 / 段距 / 页边距等排版参数**：未见文案（只有「字号」「选择字体」「句子数量」「项目符号」等零散项）。
5. **中文「标签」UI**：中文条目缺失；只能用日文检索文案中的 `_tags` 与代码里的 `user_category` / `zotero_category` 证明标签体系存在。
6. **中文「邀请」UI**：只有日文「友達を招待」「招待コードをお持ちですか？」「あなたも友達もそれぞれ {count} Agent クレジットを獲得」；中文侧的邀请页文案不在本次 harvest 结果中。
7. **托盘「登录淘宝」的正式性**：`main.js` 中该菜单项位于 `demo` 条件分支，且指向 `http://www.booktsg.com`（窗口类型 `TYPE_LOGIN_TAO_BAO`），无法确认是否为正式用户路径 → 标为「推测」。
8. **广告位的真实投放逻辑**：`checkShowPurchaseAdsEntry` 当前硬编码 `resolve(true)`，只能证明「购买入口展示位」存在，不能证明存在第三方广告投放。
9. **快捷键自定义**：仅见 `CommandOrControl+F`（应用内查找）与 `Esc`（关闭），无用户自定义快捷键设置。
10. **企业版 / 机构版 / 学校版**：无独立文案；只有坚果云「团队版」异常提示与客服入口。
11. **多端同步协议细节**：仅有进度/失败文案与 `syncManual` IPC，未见冲突合并策略（除项目文件迁移的「合并所选文件并保留本地独有内容」）。
12. **web 包本体不可用**：`web-strings.txt` 的来源文件 `main-0623db67.js`、`index-48662636.js`、`index-1d3f0da1.css` 未在 `research/` 下留存原本，仅存 TSV，因此无法做上下文级验证（例如某个占位符参数的取值、i18n key→中文的完整映射）。
13. **未取证的 HTML 页面**：`dist-tree.txt` 列出的 `net_detect.html`、`about.html`、`login_failure.html`、`add_website.html`、`search.html`、`pet.html`、`disk_space_exhaust.html` 等**未在 `research/asar/` 中解出**（只解出了 `locales/` 与 `rule/`），本文对这些页面只按存在性与主进程调用点归类，未引用其页内文案。
14. **配额具体数值**：多数额度用 `{count}`/`{quota}`/`{used}`/`{limit}` 占位，除「3 次综述报告/月」「每天 10 万字（AI 学术翻译提额至）」「5 倍 AI Agent 额度」外，未获得各档套餐的真实数值。
