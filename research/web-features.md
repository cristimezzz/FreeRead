# Scholaread（靠岸学术 / 思读）网络公开资料调研

> **归档说明（2026-10-03 仓库清理）**：本文引用的 143 条外链与一手抓取结果**全部保留在本文内**（这正是它存在的意义），未受仓库清理影响；仅文中提到的 `research/asar/`（当时的客户端解包产物）已删除，相关表述按「当时出处」理解即可。

> 调研对象：Scholaread（中文品牌「靠岸学术」，部分渠道称「思读 / scholaread」），商用 AI 论文阅读 App。
> 调研时间：**2026-10-03（Asia/Shanghai）**。
> 调研目的：为「开源论文阅读助手」项目提供竞品功能、定价、技术信号与开源替代/构建块的基线资料。

## 0. 方法与可信度说明（重要）

- 本环境自带的 `web_fetch` 工具因沙箱 DNS 把所有域名解析到非公网地址而被拒绝，**所有页面均通过 Node.js HTTPS 客户端直接抓取**（2026-10-03 当日快照），因此下文引用的一手内容为「当日官网/官方接口真实返回」。
- 引用分级：
  - **官方接口 / 官方页面**（help 文档、隐私政策、购买协议、发布通道 yml、App Store/Google Play/Chrome 应用商店元数据、官网前端 JS 资源中的 i18n 文案）＝高可信。
  - **官方自荐帖 / 官方博客**（appinn 开发者自荐帖、官网 blog）＝中可信（营销口径，可能与实际实现有差距）。
  - **第三方测评 / 商店评论**＝低可信但可用于用户口碑。
  - 未能直接验证的条目一律标注「**未验证**」。
- 关于厂商主体：官方中英文协议、App Store 与 Google Play 元数据、站点页脚**均指向两家实体**：
  - 中国主体：**上海亦答网络科技有限公司**（即坚果云 Nutstore 的运营主体）——见[专业版用户购买协议](https://www.scholaread.cn/help/purchase-agreement)、[服务协议](https://www.scholaread.cn/help/terms)、[Zotero 落地页页脚](https://www.scholaread.cn/landing/zotero)。
  - 海外主体：**Astronet Technology PTE. LTD.**（新加坡）——见[英文购买协议](https://www.scholaread.com/help/purchase-agreement)、[Chrome 应用商店开发者信息](https://chromewebstore.google.com/detail/save-to-scholaread/fmnecdkodmebkjieiiihcpefkkgapnap)、Google Play 开发者信息。
  - ⚠️ 任务书中提到的「上海阅知信息科技」**在本次可核实的官方材料中未出现**（未验证）。可确证的主体是「上海亦答网络科技有限公司 / Astronet Technology PTE LTD」。

---

## 1. 定位与平台

### 1.1 一句话定位

面向科研人员（研究生、博士生、需要大量读英文文献的学者）的**「阅读 + 翻译 + 文献管理 + AI 研究助手 + 写作引用」一体化商业软件**，核心卖点是：

1. **自研 PDF 版面解析 + AI 重排**：把双栏论文重排成适配手机/平板的单栏流式排版；
2. **逐段中英对照翻译**（学术翻译引擎）；
3. **多端云同步**（桌面/移动/Web 六端）；
4. 近两个大版本叠加 **AI Agent 研究协作 + AI 综述 + 引用助手**（来源：[开发者自荐帖](https://meta.appinn.net/t/topic/88647)、[官网帮助中心](https://www.scholaread.cn/help/about)）。

官方愿景原文：「通过先进的 PDF 排版解析算法，我们将复杂排版的文献转换成适合屏幕的简洁版式……逐段对照全文翻译」（[关于我们](https://www.scholaread.cn/help/about)）。

### 1.2 平台与客户端矩阵

| 平台/形态 | 说明 | 来源 |
|---|---|---|
| Windows | Windows 10 及以上，**仅 x64，暂不支持 ARM** | [全平台同步说明](https://www.scholaread.cn/help/pc-faq-16) |
| macOS | macOS 11.0+，分 Intel / Apple Silicon 两版 | 同上 + [下载配置接口](https://www.scholaread.cn/api/configs/version) |
| Linux | Ubuntu 20.04+（发布物为 `.deb`） | 同上 + [latest-linux.yml](https://cdn.scholaread.cn/assets/pc-releases/1.1.86/cn/latest-linux.yml) |
| iOS / iPadOS | iOS 15.0+（iPhone + iPad） | [App Store 元数据](https://itunes.apple.com/lookup?id=6473978803&country=cn) |
| Android | 7.0+（国内包 `com.scholaread.cn`，海外包 `com.scholaread`） | [全平台同步说明](https://www.scholaread.cn/help/pc-faq-16)、[版本接口](https://www.scholaread.cn/api/configs/version) |
| Web 版 | Chrome / Edge / Safari / Firefox，免安装；**部分功能（如项目文件管理）仅桌面客户端** | [全平台同步说明](https://www.scholaread.cn/help/pc-faq-16) |
| 浏览器扩展 | 「Save to Scholaread」：自动识别 arXiv、IEEE、Elsevier、Springer、ACM、MDPI 等站点一键保存；商店显示 3,000 用户 | [Chrome 应用商店](https://chromewebstore.google.com/detail/save-to-scholaread/fmnecdkodmebkjieiiihcpefkkgapnap) |
| 书签小工具（bookmarklet） | 官网前端枚举了导入来源 `bookmarklet` | 官网前端 JS 资源（i18n/枚举） |
| Zotero 集成 | **桌面客户端读取本地 Zotero 数据库导入**，保留文件夹层级；设置中有「Zotero 集成」开关与「Zotero 阅读助手」 | [如何导入文献](https://www.scholaread.cn/help/pc-faq-3) |
| Word / WPS 插件 | 「Word 参考文献引用助手」，支持 Windows Word 2013+、macOS Word 2016+、网页版；插件本身**永久免费**；前端文案显示 Word 写作插件曾以内测形式发布 | [参考文献引用助手](https://www.scholaread.cn/help/pc-faq-14-2)、[英文帮助中心](https://www.scholaread.com/help)、官网前端文案 |
| Microsoft Store | 有上架条目（x64）；页面为 JS 渲染，商店接口返回的发布者字段指向深圳的一家公司实体（**与官网主体不一致，未验证原因**） | [MS Store 页面](https://apps.microsoft.com/detail/xp9csmsz1w14lc) |

> **当前 PC 客户端版本：1.1.86**（发布日 2026-09-28），更新内容为「Agent 技能商店（首批：生成 PPT、极简论文拆解）+ 消息发送队列」。iOS 国内版 1.9.17 / 1.9.1（接口口径），Android 国内版 1.9.8，海外 Android 1.3.0。来源：[版本接口](https://www.scholaread.cn/api/configs/version)、[App Store 元数据](https://itunes.apple.com/lookup?id=6473978803&country=cn)、[latest.yml](https://cdn.scholaread.cn/assets/pc-releases/1.1.86/cn/latest.yml)。

---

## 2. 功能清单（分组）

### 2.1 PDF 阅读与渲染 / 版面重排

| 能力 | 细节 | 来源 |
|---|---|---|
| 双模式阅读 | 「AI 重排模式」与「原文 PDF 模式」一键切换 | [重排模式](https://www.scholaread.cn/help/pc-faq-4) |
| AI 重排（AI 排版引擎） | 自动把双栏 PDF 解析为单栏流式排版，「像看公众号文章」；解析元素含文本、目录、图片、表格、注释；官方称可处理 95% 的复杂文档内容（图像、复杂表格、LaTeX 公式） | [重排模式](https://www.scholaread.cn/help/pc-faq-4)、官网前端套餐文案 |
| 重排上限 | 官方前端提示「AI 重排最多支持 N 页 / N 大小」，超出报错；用户评论中也提到页数上限（希望提到 1000 页） | 官网前端文案、[App Store 评论](https://itunes.apple.com/cn/rss/customerreviews/id=6473978803/sortBy=mostRecent/json) |
| 公式保留 | 官方自荐帖称「数学公式被单独识别并保留原样」；图表/公式可单独放大、截图 | [开发者自荐帖](https://meta.appinn.net/t/topic/88647)、[AI 阅读辅助](https://www.scholaread.cn/help/pc-faq-9) |
| 自动目录 | 自动生成小标题目录，可跳转，识别错误可反馈 | [移动端目录](https://www.scholaread.cn/help/app-faq-3) |
| 引文即点即看 | 点击正文引用标注弹出文献信息（标题/作者/摘要/速读），可一键加入文献库 | [AI 阅读辅助](https://www.scholaread.cn/help/pc-faq-9) |
| 图表集中提取 | 侧边栏汇总全文图表缩略图，点击放大/定位 | 同上 |
| 字体/字号/背景 | 重排模式可切换字体、调节字号，并可设背景色 | [重排模式](https://www.scholaread.cn/help/pc-faq-4)、[全平台同步](https://www.scholaread.cn/help/pc-faq-16) |
| 双语重排 PDF 导出 | 支持把重排后的双语全文导出为 PDF（含高亮与笔记），**仅电脑客户端**；免费版无额度（0 次），Pro/Pro Max 每月 10 次 | [官方权益接口](https://www.scholaread.cn/api/configs/pricing_account_state_rights)、官网前端套餐文案 |
| 支持格式 | PDF、**CAJ**（知网格式）；批量上传单次最多 12 个文件 | [如何导入文献](https://www.scholaread.cn/help/pc-faq-3) |

### 2.2 OCR 与影印版处理

| 能力 | 细节 | 来源 |
|---|---|---|
| 截图 OCR 翻译 | 平板端「原文模式」下框选区域截图翻译，可手工修正识别错误后重译；官方标注**目前仅推荐 Apple iPad** | [iPad 截屏翻译](https://www.scholaread.cn/help/app-faq-6) |
| PC 划词翻译 / OCR 截图翻译 | Pro 权益含「OCR 翻译、划词翻译」，免费版每天 3 次，Pro **无限** | [官方权益接口](https://www.scholaread.cn/api/configs/pricing_account_state_rights)、官网套餐表 |
| 影印/扫描版支持程度（**官方自相矛盾**） | 套餐页宣称「影印版 PDF 重排 & 翻译」；但翻译 FAQ 明确写「**影印或扫描版文章以图片形式存在，暂时无法翻译**」，需用截屏翻译绕过 | 官网套餐表 vs [翻译功能常见问题](https://www.scholaread.cn/help/translation-faq) |
| 未发现的能力 | 未在官方材料中发现「自动 OCR 全文重建为可选中文本」的端到端扫描件重排能力（**未验证/可能不存在**） | — |

### 2.3 翻译

| 能力 | 细节 | 来源 |
|---|---|---|
| 逐段中英对照 | 重排后「原文 + 译文」逐段对照；对照式翻译为核心卖点 | [对照式翻译](https://www.scholaread.cn/help/pc-faq-6) |
| 语言数量 | 官方口径 **17 种语言互译**（App Store 文案列举英/法/德/日/韩等） | [开发者自荐帖](https://meta.appinn.net/t/topic/88647)、[App Store 元数据](https://itunes.apple.com/lookup?id=6473978803&country=cn) |
| 专业术语 | 主打「学术场景优化 / 专业术语准确」，宣传语称译文会保留英文术语；**未发现用户可自定义的术语库/glossary 功能**（未验证其存在） | [开发者自荐帖](https://meta.appinn.net/t/topic/88647) |
| 划词翻译 | 选中文字即时翻译/解释 | [AI 问答](https://www.scholaread.cn/help/pc-faq-11) |
| 图表/公式翻译 | 官方称「图表公式翻译引擎」可翻译提取公式、图片、代码 | [App Store 元数据](https://itunes.apple.com/lookup?id=6473978803&country=cn) |
| 翻译缓存与额度 | 已翻译内容临时缓存在**本地设备**，重复阅读不重复扣额度（手动重译/换设备/清缓存除外） | [翻译功能常见问题](https://www.scholaread.cn/help/translation-faq) |
| 翻译引擎品牌 | 官方仅称「专业学术翻译引擎」「自研」；**未声明任何第三方引擎（DeepL/Google/百度等）**。前端 JS 资源中亦未发现第三方翻译引擎字样 | 官网前端 JS 资源（grep 无命中） |
| 已知缺陷（官方承认） | 切换排版模式时可能自动补译；排版异常会出现译文乱码；新导入文章需数秒至数分钟转换 | [翻译功能常见问题](https://www.scholaread.cn/help/translation-faq) |

### 2.4 AI 功能

**(a) 单篇 AI 问答 / AI 阅读**

| 能力 | 细节 | 来源 |
|---|---|---|
| 常驻侧边栏问答 | 基于当前文献回答，回答标注引用段落与页码，可点击跳转 | [AI 问答](https://www.scholaread.cn/help/pc-faq-11) |
| 快捷指令 | 一键「总结论文」「梳理论文大纲」「生成学习指南」 | 同上 |
| 划词提问/解释 | 选中术语、长难句、复杂公式 → 「AI 解释」 | 同上 |
| 公式与图表解释 | 选中公式得到语言化描述；图表可点「AI 解释」或直接问「解释图 3」；官方自荐帖称支持 **30+ 种图表类型** | [AI 问答](https://www.scholaread.cn/help/pc-faq-11)、[开发者自荐帖](https://meta.appinn.net/t/topic/88647) |
| 跨篇问答 | Pro 支持**最多 20 篇文献**跨篇深度问答 | 官网套餐表（前端文案） |
| AI 阅读重点 | 自动提取并高亮四类要素：研究目标 / 方法 / 主要结论 / 创新点，侧边栏按类汇总，原文句子非摘要改写 | [AI 阅读重点](https://www.scholaread.cn/help/pc-faq-10) |
| 文献速览 | 悬停文献即弹出「秒懂速读」、摘要（可翻译）、元数据与图表预览 | [AI 阅读辅助](https://www.scholaread.cn/help/pc-faq-9) |

**(b) AI 文献综述（研究报告）**

- 输入研究方向 → 并行检索多个学术库（官方点名的有 PubMed、arXiv、IEEE Xplore、中国知网）→ 筛出约 100 篇候选 → 提取 15+ 篇核心文献 → 生成 **10,000 字以上**结构化综述，含研究背景/方法演进/技术对比/现状/问题/展望；**约 30 分钟内完成**；支持导出 Markdown；引用可一键溯源到原文 PDF（[AI 文献综述](https://www.scholaread.cn/help/pc-faq-17)、[Agent 更新日志](https://www.scholaread.cn/blog/?p=239)）。
- 额度（官方接口）：免费 0 篇/月，Pro 3 篇/月，Pro Max 10 篇/月；另有可单独购买的「深度研究报告加油包」（见 §3）。

**(c) 研究 Agent（Beta）**

- 组织模型：**项目 = 研究空间**，内含「项目会话」（与 Agent 的对话）与「项目文件」（草稿、CSV、报告、实验结果等，Markdown 可在线编辑）；论文本身仍留在文献库（[核心概念](https://www.scholaread.cn/help/key-concepts)）。
- 资料来源：文献库论文/文件夹、外部学术来源、网页 URL、**浏览器页面**（Agent 可打开、读取、截图、点击、输入、滚动、关闭页面）（[Agent 能做什么](https://www.scholaread.cn/help/agent)）。
- 支持 `@` 引用文献、文件夹、项目文件；支持把回答「保存回答」为项目文件（元数据记录会话标题/ID/创建时间）（[快速开始](https://www.scholaread.cn/help/getting-started)、[Agent 更新日志](https://www.scholaread.cn/blog/?p=239)）。
- 场景模板：方向评估、文献综述/related work、精读论文、复现清单与最小实验、论文大纲与润色、投稿前自查（模拟审稿人）、审稿意见拆解与 rebuttal 计划、生成汇报材料（[科研场景](https://www.scholaread.cn/help/scenario)）。
- 风险边界：改文件、改文献库、执行分析脚本、操作浏览器等需用户确认；「研究想法是否新颖、是否投稿」等由用户决策（[操作边界](https://www.scholaread.cn/help/boundary)、[结果检查](https://www.scholaread.cn/help/result-check)）。
- 前端资源中还出现「多 Agent 协作进行中…」「上下文自动压缩」「工具调用/工具结果」等内部阶段文案，说明其 Agent 具备工具调用与上下文压缩机制（官网前端 JS 资源；实现细节 **未验证**）。
- 平台限制：项目文件管理「仅桌面客户端支持」，移动端有独立的 `mobile-agent` 资源包（版本 v1.0.6）（官网前端文案、[版本接口](https://www.scholaread.cn/api/configs/version)）。
- 外部集成：前端文案含「连接至 OpenAI —— 在 ChatGPT 中使用 Scholaread」以及带有效期/最近使用时间的「集成密钥（integration key）」，指向对外提供的连接器/密钥能力（**具体形态未验证**）。

**(d) 额度口径**（AI 相关，官方公开接口）

| 权益项 | 免费版 | Pro | Pro Max |
|---|---|---|---|
| AI 学术翻译 | 7,000 字/天 | 100,000 字/天 | 200,000 字/天 |
| AI PDF 解析 & 重排 | 50 页/天 | 500 页/天 | 1,000 页/天 |
| OCR 翻译 / 划词翻译 | 3 次/天 | 无限 | 无限 |
| AI 问答 | 5 次/天 | 50 次/天 | 100 次/天 |
| AI Agent 额度 | 150/月 | 2,000/月（≈20–25 轮复杂任务） | 10,000/月（≈100–150 轮） |
| AI 综述报告（深度研究） | 0/月 | 3/月 | 10/月 |
| 双语重排 PDF 导出 | 0/月 | 10/月 | 10/月 |
| 单篇上传大小 | 50 MB | 200 MB | 300 MB |

来源：[`/api/configs/pricing_account_state_rights`](https://www.scholaread.cn/api/configs/pricing_account_state_rights)（`-1` = 无限）、官网套餐表前端文案。

### 2.5 知识管理与文献管理

| 能力 | 细节 | 来源 |
|---|---|---|
| 文件夹体系 | 多级树状文件夹、实时文献计数、卡片/列表双视图 | [文献管理](https://www.scholaread.cn/help/pc-faq-12) |
| 标签 | 支持标签与二级标签，可按标签搜索 | [标签/搜索相关帮助页](https://www.scholaread.cn/help/pc-faq-8) |
| 元数据 | 导入即自动解析标题/作者/摘要/期刊/年份/DOI；可手工补 DOI、URL、卷期页码、ISSN 等 | [文献管理](https://www.scholaread.cn/help/pc-faq-12)、[引用助手](https://www.scholaread.cn/help/pc-faq-14-2) |
| 库内搜索 | 标题/作者/摘要多字段匹配 + 关键词高亮 + 二次过滤 | [文献管理](https://www.scholaread.cn/help/pc-faq-12) |
| 高亮 | 多色高亮、侧边栏「高亮笔记」聚合、点击定位原文 | [高亮、笔记](https://www.scholaread.cn/help/pc-faq-13) |
| 笔记 | 与段落锚定的文本笔记，可编辑、时间戳、复制、删除、导出为独立文档；可按文件夹/标签筛选 | 同上 |
| 手写批注 | iPad/安卓平板手写（Apple Pencil 压感、S Pen、铅笔/钢笔/荧光笔），**仅在原文模式**下可用，独立图层存储，导出时可选是否含手写 | 同上 |
| 阅读状态 | 保存阅读位置、访问历史、阅读时长、书签；跨设备接力（示例：iPad 第 15 页 → 桌面端自动跳第 15 页） | [全平台同步](https://www.scholaread.cn/help/pc-faq-16) |
| 云同步 | 文献原文件、文件夹结构、标签、阅读状态、高亮笔记、AI 会话、界面偏好全同步；宣称加密存储、全球 CDN、**常用文献本地缓存支持离线阅读**、增量同步/断点续传 | 同上 |
| 引用与导出 | 详情页一键导出 9 种格式：GB/T 7714-2015、APA、MLA、IEEE、Chicago、Harvard、Vancouver、BibTeX、RIS（引用助手中另列 Bluebook、OSCOLA 共 7 种内置格式） | [文献管理](https://www.scholaread.cn/help/pc-faq-12)、[引用助手](https://www.scholaread.cn/help/pc-faq-14-2) |
| 写作插件 | Word/WPS：语义推荐文献、插入引用、一键全文换格式、自动参考文献列表、AI 论文格式检查（含 GB/T 7714 国标检测、自定义规则、批量修改） | [引用助手](https://www.scholaread.cn/help/pc-faq-14-2) |
| Zotero | 客户端读取本地 Zotero 库，保留文件夹层级，识别「已在文献库 / x 篇更新」，支持选择性导入 | [如何导入文献](https://www.scholaread.cn/help/pc-faq-3) |
| 存储承诺 | 落地页宣称「上传不限量不限速，容量全免费」（对比 Zotero 免费 300 MB） | [Zotero 落地页](https://www.scholaread.cn/landing/zotero) |

### 2.6 搜索与发现

- **库内搜索**：标题/作者/摘要（见上）。
- **全网学术搜索**：Agent 侧「全网搜论文」覆盖 arXiv、PubMed、IEEE 等，按被引频次/日期/匹配度排序，回答生成综述式列表并可点链接下载 PDF（[Agent 更新日志](https://www.scholaread.cn/blog/?p=239)）。
- **一键保存**：浏览器扩展自动识别 arXiv、IEEE、Elsevier、Springer、ACM、MDPI 等站点；前端枚举的导入来源还包括书签工具、链接、Twitter/Reddit bot、`search_scholar`（搜索导入）、`share_id`（分享导入）等（[Chrome 应用商店](https://chromewebstore.google.com/detail/save-to-scholaread/fmnecdkodmebkjieiiihcpefkkgapnap)、官网前端枚举）。
- **引用发现**：正文引文点击后可加入文献库，形成引文网络式延伸阅读（[AI 阅读辅助](https://www.scholaread.cn/help/pc-faq-9)）。
- **数据源致谢**：官方「致谢」页唯一点名的第三方学术数据源是 **Semantic Scholar API**（[致谢](https://www.scholaread.cn/help/acknowledgment)）。

### 2.7 协作 / 分享

- **分享**：支持生成分享链接（前端存在 `share_id` 数据模型与社交分享组件：Twitter/Reddit/Email 等）；未见实时多人协同编辑（官网前端资源）。
- **跨地点协作**：官方同步页举了「导师批注 → 学生实时看到」的例子，但机制是**各自账号 + 文件同步**，不是共享库/团队空间（[全平台同步](https://www.scholaread.cn/help/pc-faq-16)）。
- **团队版**：仅出现在坚果云联售套餐语境（绑定的坚果云账号为团队版时无法升级 Pro）（官网前端文案）。
- **账号限制**：协议禁止共享账号，多设备多地登录会被封禁；前端提示「您的账号已在多台同类型设备上登录，当前设备登录状态已失效」（[购买协议 1.4](https://www.scholaread.cn/help/purchase-agreement)、官网前端文案）。

### 2.8 其他 / 可访问性

| 能力 | 状态 | 来源 |
|---|---|---|
| 深色模式 | **有**：深色 / 浅色 / 跟随系统 | 官网前端设置文案 |
| 桌面宠物 | **有**：设置项含「桌面宠物」 | 官网前端设置文案 |
| 阅读背景色/字号/字体 | 有 | 官网前端设置文案 |
| 界面语言 / AI 回复语言 | 简体中文 / English 独立设置（AI 回复语言与界面语言可分离） | [切换语言](https://www.scholaread.cn/help/pc-faq-11-2) |
| 广告 | **免费版含广告**（隐私政策披露接入腾讯广告「优量汇」SDK）；Pro 权益含「无广告沉浸阅读」 | [隐私政策](https://www.scholaread.cn/help/privacy)、官网套餐表 |
| 朗读 / TTS | **未发现任何证据**（在官网前端全量文案与帮助中心中检索「朗读/TTS/语音/听书」均无产品功能命中）——判定为**该产品当前无朗读功能** | 官网前端 JS + 帮助中心全文检索 |
| 无障碍 | 未发现 WCAG/无障碍相关声明（未验证） | — |

---

## 3. 价格与授权（重要）

### 3.1 免费版 vs 付费版（官方公开接口）

- 额度对照见 §2.4(d)。补充：免费版**无** AI 综述报告额度、**无**双语重排 PDF 导出额度；免费版 AI 问答 5 次/天；免费版上传上限 50 MB/篇。
- 套餐结构（官网前端 i18n）：`basic`（免费体验版）/ `pro`（专业版）/ `proMax`（专业版 Max）；支付渠道枚举为 `alipay`、`wechat`（扫码）、`stripe`、`apple`、`lenovo`。协议规定计费周期为**按季度、按年**（[购买协议 2.1](https://www.scholaread.cn/help/purchase-agreement)）。

### 3.2 实际价格（来自官方计费配置接口，单位：分）

**人民币（provider=alipay，一次性购买）** — 来源：[`/api/pay/configs?provider=alipay&type=account_state_pro_pay`](https://www.scholaread.cn/api/pay/configs?provider=alipay&type=account_state_pro_pay)

| 商品 | 现价 | 原价 | 折扣标签 |
|---|---|---|---|
| 专业版 季付 | ¥109.00 | ¥109.00 | — |
| 专业版 年付 | **¥199.90** | ¥429.90 | 54% off |
| 专业版 Max 季付 | ¥299.00 | ¥299.00 | — |
| 专业版 Max 年付 | **¥699.00** | ¥1,299.00 | 46% off |
| Agent 额度加油包（月） | ¥19.90 | ¥29.90 | — |
| 深度研究报告加油包（月） | ¥29.90 | ¥29.90 | — |

> 注：该接口的 `pays` 列表**未包含「专业版月付」**，即在支付宝渠道下当前仅提供季付/年付（月付仅存在于套餐文案中，**月付是否在售未验证**）。
> 开发者自荐帖口径一致：「基础功能免费（含每日有限翻译额度）；专业版订阅 109 元/季，199 元/年。Word/WPS 引用插件完全免费。」（[appinn 开发者自荐帖](https://meta.appinn.net/t/topic/88647)）

**美元（provider=stripe，订阅）** — 来源：[`/api/pay/configs?provider=stripe&type=account_state_pro_sub`](https://www.scholaread.cn/api/pay/configs?provider=stripe&type=account_state_pro_sub)

| 商品 | 现价 | 原价 | 折扣 |
|---|---|---|---|
| Pro 季付 | $22.80 | $22.80 | — |
| Pro 年付 | **$58.92** | $91.20 | 36% off |
| Pro Max 季付 | $59.00 | $59.00 | — |
| Pro Max 年付 | **$179.00** | $249.00 | 28% off |
| Agent 额度加油包（月） | $3.99 | $4.99 | — |
| 深度研究报告加油包（月） | $4.99 | $4.99 | — |

**联售/捆绑**：国内存在与**坚果云**的联售套餐（购买需绑定坚果云账号并用支付宝支付），额外赠「坚果云 Pro、坚果云 AI 写作、怡氧」等一年订阅（官网前端文案；[联售购买 FAQ](https://www.scholaread.cn/help/nutstore-bundle-purchase-faq)）。历史 App Store 评论也提到捆绑套餐让人「难以决定是否购买」。

**退款**：官网前端套餐文案写「**支持 7 天无理由退款**」；但[专业版购买协议 5.2](https://www.scholaread.cn/help/purchase-agreement) 明确「**专业版服务一经开通后不可退款**」。两者冲突，**以购买协议条款为准更保守**（App Store 渠道另有平台退款规则，未验证）。

**发票**：可开增值税电子普通发票，内容为「办公云存储服务费或软件服务费」（由上海亦答网络科技有限公司开具）。

### 3.3 是否闭源（结论：**闭源专有软件**）

证据链：

1. **协议明示专有**：购买协议由「上海亦答网络科技有限公司**开发、运营并享有独立知识产权**」；授予的是「个人的、有限的、可撤销的、不可转让的、非排他性的」许可，且明确「本协议未明确授权的所有其他权利仍归我们所有」（[购买协议 1.3](https://www.scholaread.cn/help/purchase-agreement)）。
2. **服务协议 4.1**：产品、技术、软件、程序、数据、输出等的全部知识产权归公司所有，禁止任何商业或非商业目的的复制、传播、镜像、下载等（[服务协议](https://www.scholaread.cn/help/terms)）。
3. **无任何公开源码渠道**：GitHub 不存在 `scholaread` 组织或用户（API 返回 404）；GitHub 代码搜索仅有 3 个同名无关仓库；官网、帮助中心均无「开源」「源码」入口（GitHub API 检索，2026-10-03）。
4. **客户端产物可反查为打包应用**：macOS 发布包（zip）内可检索到 `app.asar` 与 `Electron Framework` 字符串，为闭源打包分发（见 §4）。
5. 商业模式为订阅制 + 加量包 + 联售，且以账号封禁手段反盗用（[购买协议 1.4](https://www.scholaread.cn/help/purchase-agreement)）。

---

## 4. 技术信号（来自官方物料）

| 信号 | 结论 | 证据 |
|---|---|---|
| 桌面端框架 | **Electron（已确证）** | 发布通道文件为 electron-updater 的 `latest.yml` / `latest-mac.yml` / `latest-linux.yml` 格式（[latest.yml](https://cdn.scholaread.cn/assets/pc-releases/1.1.86/cn/latest.yml)、[latest-mac.yml](https://cdn.scholaread.cn/assets/pc-releases/1.1.86/cn/latest-mac.yml)）；进一步对 `Scholaread-mac-arm64-1.1.86.zip` 尾部做 HTTP Range 抓取，二进制内命中字符串 **`Electron Framework`** 与 **`app.asar`** |
| 打包形态 | Windows NSIS 安装包（189 MB）、macOS x64/arm64 zip + dmg（~207–221 MB）、Linux `.deb`（175 MB） | 同上 |
| 前端技术 | Web 端为 Vue 3 + Vite SPA（资源路径 `assets/web/<日期>/assets/main-*.js`，含 vue-i18n 多语言包与 Mermaid/KaTeX 等渲染库） | [官网 HTML](https://www.scholaread.cn/) 与 9.2 MB 前端 bundle |
| 富文本/公式渲染 | bundle 内含 KaTeX、Mermaid 等库（说明重排阅读器与 AI 回答支持公式/流程图渲染） | 前端 bundle |
| 翻译引擎 | 官方口径「专业学术翻译引擎 / 自研」；**未点名任何第三方翻译厂商** | 官网前端 bundle 全文检索无 DeepL/Google/百度等命中 |
| LLM 供应商 | **官方未披露**；未能在公开物料中找到 OpenAI/Anthropic/国内大模型厂商署名 | 同上 |
| 移动端 Agent | 存在独立资源包 `mobile-agent/v1.0.6/scholaread-mobile-agent.zip`（暗示移动端 Agent 运行时为可下发资源，**具体是否端侧推理未验证**） | [版本接口](https://www.scholaread.cn/api/configs/version) |
| 本地 vs 云端 | **云端为主**：文献上传到云端文献库、翻译与 AI 均在服务端；仅「翻译结果临时缓存到本设备」与「常用文献本地缓存支持离线阅读」 | [如何导入文献](https://www.scholaread.cn/help/pc-faq-3)、[翻译 FAQ](https://www.scholaread.cn/help/translation-faq)、[全平台同步](https://www.scholaread.cn/help/pc-faq-16) |
| 第三方基建 | 登录与存储深度绑定**坚果云（Nutstore）**账号体系；Google/Apple/微信/企业微信登录；支付 Stripe/支付宝/微信/联想 | 官网前端文案、[Chrome 商店](https://chromewebstore.google.com/detail/save-to-scholaread/fmnecdkodmebkjieiiihcpefkkgapnap) |
| 第三方 SDK（隐私披露） | 火山引擎（数据统计）、Bugly（崩溃）、**腾讯广告优量汇**（广告）；采集 Android_ID、OAID、设备序列号、安装列表、粗略位置等 | [隐私政策](https://www.scholaread.cn/help/privacy) |
| 数据存储地 | 中国境内（并称目前不向境外传输个人信息） | [隐私政策 6.1](https://www.scholaread.cn/help/privacy) |
| 学术数据源 | 唯一公开署名：Semantic Scholar API | [致谢](https://www.scholaread.cn/help/acknowledgment) |
| Google Play「数据安全」自述 | 声明「不与第三方分享任何数据、不收集任何数据」——与其隐私政策中列出的多个第三方 SDK 明显冲突，**商店声明可信度低** | [Google Play](https://play.google.com/store/apps/details?id=com.scholaread) vs [隐私政策](https://www.scholaread.cn/help/privacy) |

---

## 5. 开源生态与可复用构建块

> 下列星标/许可/最近提交时间为 **2026-10-03 通过 GitHub REST API + LICENSE 原文核验**（每个仓库的 license 字段与 LICENSE 文件内容均已读取确认，故与社区常见印象不同的已特别注明）。

### 5.1 端到端「同类产品」开源项目

| 项目 | 许可 | 技术栈 | 星标 | 最近活动 | 擅长 / 不足 |
|---|---|---|---|---|---|
| [Zotero](https://github.com/zotero/zotero) | **AGPL-3.0**（COPYING 原文确认） | JavaScript/Electron | 15.5k | 活跃（2026-10-02） | 文献管理事实标准，Zotero 7 内置 PDF 阅读器可高亮/笔记；不足：**无重排、无 AI、无逐段对照翻译**，插件生态补足 |
| [zotero-pdf-translate](https://github.com/windingwind/zotero-pdf-translate) | AGPL-3.0 | TypeScript | 12.0k | 活跃（2026-10-01） | Zotero 内 PDF/EPUB/网页/元数据/笔记翻译，支持 20+ 翻译服务；不足：翻译需自备 API，排版仍为原 PDF 版式（不重排） |
| [zotero-better-notes](https://github.com/windingwind/zotero-better-notes) | AGPL-3.0 | TypeScript | 8.3k | 活跃（2026-08） | 笔记管理与模板化；不足：与翻译/重排无关 |
| [zotero-gpt](https://github.com/MuiseDestiny/zotero-gpt) | AGPL-3.0 | TypeScript | 7.4k | 2026-05 | Zotero 内 GPT 问答；不足：需自备 key，无重排，issue 积压较多（247 open） |
| [Aria（ai-research-assistant）](https://github.com/lifan0127/ai-research-assistant) | AGPL-3.0 | JavaScript | 1.7k | **放缓**（2025-04-01 最后提交） | Zotero 内 AI 研究助手（问答、摘要）；不足：维护活跃度下降 |
| [Better BibTeX](https://github.com/retorquere/zotero-better-bibtex) | MIT | TypeScript | 7.2k | 活跃 | LaTeX/BibTeX 引用键与导出；不足：仅引用管理 |
| [JabRef](https://github.com/JabRef/jabref) | MIT | Java | 4.8k | 活跃 | BibTeX/BibLaTeX 管理器 |
| [Paperlib](https://github.com/Future-Scholars/paperlib) | GPL-3.0 | TypeScript/Electron | 2.3k | 2026-04 | 开源文献管理（含跨库检索、元数据抓取）；不足：社区较小、无重排/AI 翻译 |
| [KOReader](https://github.com/koreader/koreader) | AGPL-3.0 | Lua | 30.1k | 活跃 | 电子墨水设备 PDF/EPUB 阅读之王（重排、字典、批注）；不足：面向墨水屏、无云同步/学术元数据/AI |
| [Calibre](https://github.com/kovidgoyal/calibre) | GPL-3.0 | Python/Qt | 26.1k | 活跃 | 电子书管理与转换；不足：面向图书而非论文流，无 AI/翻译工作流 |
| [Readarr](https://github.com/Readarr/Readarr) | GPL-3.0 | C# | 3.5k | **已归档（2025-06）** | 图书自动化管理；**不推荐作为基础**（项目已 archived） |
| [Obsidian PDF++](https://github.com/RyotaUshio/obsidian-pdf-plus) | MIT | TypeScript | 2.5k | 2025-08 | 在 Obsidian 内做 PDF 标注并双向链接笔记；不足：绑定 Obsidian 私有格式、无翻译/重排 |
| [Sioyek](https://github.com/ahrm/sioyek) | GPL-3.0 | C++/Qt | 9.9k | 代码活跃（2026-09-24），但**最新 release 仍是 v2.0.0（2022-12）** | 面向论文/教材的键盘流 PDF 阅读（portals、类 Vim 跳转、参考文献跳转）；不足：无移动端、无云同步、无 AI、无翻译，且长期不发正式版本 |
| [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate) | AGPL-3.0 | Python | 37.3k | 活跃（2026-10-02） | **最接近 Scholaread 翻译重排的开源件**：保留排版的 PDF 全文双语翻译，支持 Google/DeepL/Ollama/OpenAI 等，提供 CLI/GUI/MCP/Docker/Zotero |
| [zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh) | AGPL-3.0 | TypeScript/Python | 7.1k | 2026-09 | 把 PDFMathTranslate 接入 Zotero 的插件；不足：需本地部署服务 |
| [PaperQA2](https://github.com/Future-House/paper-qa) | Apache-2.0 | Python | 9.3k | 活跃（2026-09-25） | 高精度科学文献 RAG 问答（带引用的 agentic RAG）；不足：库/CLI 形态，无 UI 与阅读器 |

**闭源对照产品（非开源）**：

| 产品 | 形态与价格 | 来源 |
|---|---|---|
| SciSpace（Typeset） | 闭源 SaaS；Basic $0、Premium $12/月（年付）或 $20/月、Advanced $70/$90、Max $160/$200，含 Agent 额度体系 | [SciSpace 定价](https://scispace.com/pricing)、[额度说明](https://scispace.com/resources/credits-pricing-guide/) |
| ChatPDF | 闭源；免费每天 2 份文档，Plus 无限；官方称在 GPT‑4o/4o‑mini 间动态路由；支持 PDF/DOCX/PPTX/MD/TXT 与分享链接 | [chatpdf.com](https://www.chatpdf.com/) |
| ReadPaper（中文） | 闭源；免费云端同步 200 篇文献，浏览器插件导入、Word 插件 + BibTeX（称支持 20000+ 格式）、学术社区/小组协同 | [readpaper.com](https://readpaper.com/) |

### 5.2 解析 / 版面 / OCR 构建块

| 组件 | 许可（已核验） | 语言 | 星标 | 最近活动 | 擅长 / 注意 |
|---|---|---|---|---|---|
| [PDF.js](https://github.com/mozilla/pdf.js) | Apache-2.0 | JS | 54.0k | 活跃 | 浏览器端 PDF 渲染事实标准，可直接作为开源阅读器的渲染层 |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | MIT | Python | 10.8k | 2026-08 | 字符级/表格级精确提取，适合数字版 PDF |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | **AGPL-3.0**（需商业授权可闭源使用） | Python/C | 10.8k | 活跃 | 性能极佳（文本/图片/注释/渲染）；**AGPL 传染性最强，闭源商业产品必须买商业许可** |
| [GROBID](https://github.com/kermitt2/grobid) | Apache-2.0 | Java | 5.2k | 0.9.1 @ 2026-08-04 | 学术 PDF 元数据/结构/引文抽取的经典方案，稳定、许可友好 |
| [Marker](https://github.com/datalab-to/marker) | **Apache-2.0**（LICENSE 原文已核验；社区常误传为 GPL-3.0，属旧版许可） | Python | 40.2k | v2.0.0 @ 2026-07-20 | PDF→Markdown/JSON 高精度，含公式/表格；商业友好 |
| [Surya](https://github.com/datalab-to/surya) | Apache-2.0 | Python | 21.4k | 2026-09 | OCR/版面/阅读顺序/表格识别（90+ 语言），Marker 的底层 |
| [Docling](https://github.com/docling-project/docling) | **MIT** | Python | 68.3k | 活跃（2026-10-02） | IBM 系文档解析，许可最宽松，生态增长快 |
| [MinerU](https://github.com/opendatalab/MinerU) | **Apache-2.0 + 附加条款**（非纯 Apache） | Python | 81.0k | mineru-4.0.10 @ 2026-09-29 | 中文生态最强；附加条款要求：MAU > 1 亿或月营收 > 2000 万美元需另行购买商业许可，**在线服务必须显著标注使用了 MinerU** |
| [Nougat](https://github.com/facebookresearch/nougat) | **代码 MIT，模型权重 CC-BY-NC** | Python | 10.1k | 停滞（2025-02） | 学术 PDF→LaTeX 的经典模型；**权重非商用**，商用项目不可直接使用 |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Apache-2.0 | Python | 90.5k | 2026-09 | 100+ 语言 OCR，许可友好、中文强 |
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | Apache-2.0 | Python | 15.5k | 活跃 | 通用文档 ETL |
| [PDF-Extract-Kit](https://github.com/opendatalab/PDF-Extract-Kit) | AGPL-3.0 | Python | 10.0k | 停滞（2025-01） | 版面/公式/表格组合工具包；被 MinerU 取代趋势 |
| [pdf2htmlEX](https://github.com/pdf2htmlEX/pdf2htmlEX) | **GPLv3（整体包）** | C++/HTML | 5.6k | 维护停滞（最后 release 2020，最后提交 2025-07） | 保留版式的 PDF→HTML；**GPL 传染 + 项目老化**，新项目建议改用 Docling/Marker/PyMuPDF+自研排版 |

### 5.3 许可影响小结（给开源项目的直接结论）

1. **AGPL-3.0 是最大雷区**：Zotero、PyMuPDF、PDFMathTranslate、zotero-pdf2zh、KOReader、Aria、zotero-gpt、Better Notes、pdf-translate 均为 AGPL。若我们的阅读器以 **网络服务** 形式对外提供，AGPL 要求向用户提供对应源码（含修改）；以桌面端分发时则以 GPL 系条款要求整体开源。**"引用/调用 AGPL 组件" 不等于可以闭源，需法务确认链接方式**。
2. **许可友好的核心组合**：PDF.js（Apache）+ Docling（MIT）/ Marker（Apache）+ GROBID（Apache）+ PaddleOCR/Surya（Apache）+ PaperQA2（Apache）可构成「渲染 + 解析 + 元数据 + OCR + RAG 问答」的商业友好底座。
3. **注意"假友好"**：Nougat 权重 CC-BY-NC（**不可商用**）；MinerU 是 Apache+附加条款（大厂阈值 + 强制署名）；pdf2htmlEX 是 GPLv3。
4. **PyMuPDF** 若要用（性能确实最好），AGPL 之外必须购买 Artifex 商业许可；否则改用 pdfplumber（MIT，速度较慢）+ PDF.js 渲染。
5. **Zotero 生态**：Zotero 本体 AGPL，其插件生态基本也选 AGPL；若我们做 Zotero 插件集成，**插件自身需按 AGPL 发布**（并可复用 Zotero 的 Connectors/translators 生态，注意 Zotero 商标）。
6. **翻译层**：PDFMathTranslate 已支持 Google/DeepL/Ollama/OpenAI 等多种后端（AGPL）；若要闭源，需要自研同等「版面保留 + 双语对照」管线（Docling/Marker 出结构化块 → 逐块翻译 → 重新排版）。

---

## 6. 用户评价与投诉（第三方，低可信但真实）

### 6.1 量化口碑

| 渠道 | 评分 | 备注 |
|---|---|---|
| App Store 中国区 | **4.63 / 5（1,471 条评分）**，当前版本同分 | [itunes lookup](https://itunes.apple.com/lookup?id=6473978803&country=cn) |
| Google Play | **4.4 / 5（37 条）**，10,000+ 次下载 | [Google Play](https://play.google.com/store/apps/details?id=com.scholaread) |
| Chrome 扩展「Save to Scholaread」 | **1.3 / 5（7 条）**，版本 1.0.3，**最后更新 2023-12-30**，3,000 用户 | [Chrome 应用商店](https://chromewebstore.google.com/detail/save-to-scholaread/fmnecdkodmebkjieiiihcpefkkgapnap) |

> 观察：移动端评价好且数量大，但**浏览器扩展长期未更新且评分很低**（1.3★），是产品线中最薄弱的一环。

### 6.2 具体抱怨（均来自 [App Store 评论 RSS](https://itunes.apple.com/cn/rss/customerreviews/id=6473978803/sortBy=mostRecent/json)，2026-01 ~ 2026-09）

| 类别 | 具体内容（点评级） |
|---|---|
| 稳定性 / 性能 | 「用了两天后问 AI 根本没反应/显示网络错误」（1★）；「上传后等待翻译时老闪退」（4★）；「不好用，好迟钝，还乱码」（1★）；「ai 阅读重点一直刷新不出来」（4★）；「文档一直在同步中，不能翻译，等很久都不开始」（2★） |
| 导入 / 兼容性 | 「宣传那么牛为啥用不了，导不进去」（1★）；「和我的 macbook 不兼容」（5★ 但反映问题） |
| 账号 / 同步 | 桌面用 Google 邮箱注册，**手机端没有 Google 登录选项**，担心会员与文献无法同步（3★）；iOS 上「坚果云账户无法登录，提示网络错误」（2★） |
| 阅读体验 | **每次打开回到文章开头而不是上次位置**（4★，与官方「跨设备接力」宣传冲突） |
| 额度 / 价格 | 「非专业版字数实在是太少了」（5★）；「每日字符再多一点或者按月给量更好」；「只是略贵」；希望重排页数上限提高到 1000 页；「虽然也要订阅，但排版真的舒服」 |
| 功能缺失 | 希望 iPad 增加手写笔记/文本框（该需求后续已实现）；希望支持 WPS 引用（后续已实现） |
| 捆绑销售 | 英文评论：「really requires a separate subscription plan. The bundled packages truly make it a dilemma whether to purchase or not」（4★） |
| 账号封禁争议 | 黑猫投诉存在标题为「账号被冻结，客服不帮助恢复」的投诉条目（[搜索快照](https://tousu.sina.com.cn/complaint/view/17378256654)）；**具体诉求与处理结果未能打开页面验证**。官方协议与前端逻辑确实包含"多设备多地登录视为违规共享 → 封号"的机制（[购买协议 1.4](https://www.scholaread.cn/help/purchase-agreement)） |
| 隐私顾虑（客观事实，非用户评论） | 免费版接入腾讯广告优量汇 SDK，采集设备标识符与粗略位置；免费版因此有广告，Pro 才「无广告沉浸阅读」（[隐私政策](https://www.scholaread.cn/help/privacy)） |

### 6.3 用户明确赞赏的点（对我们有参考价值）

「PDF 重排流畅、手机不用反复放大」「中英对照阅读体验好、术语准确」「AI 总结/问答省时间」「多端同步（手机/平板/电脑/iPad 手写）」「Zotero 联动」「导出/引用格式」「无广告（付费后）」「Agent 对综述与找资料有帮助」。

---

## 7. 对我们（开源论文助手）的启示（简明）

1. **必须对齐的"及格线"功能**：AI 重排（双栏→单栏）+ 逐段双语对照 + 多端同步与阅读进度接力 + 高亮/笔记 + Zotero 导入 + 引文即点即看 + 图表聚合。这些是用户口碑的核心，而非 AI Agent。
2. **差异化机会点**（Scholaread 的已知短板）：离线/本地优先（其翻译与 AI 强依赖云端）、可自定义术语库、扫描件端到端 OCR 重排（其官方承认扫不出）、不封号/不绑第三方账号、无广告、浏览器扩展维护（其扩展 1.3★ 且 2023 年后未更新）、跨文献问答条数与额度不设商业限制。
3. **技术选型建议**：渲染 PDF.js（Apache）；结构化解析优先 Docling（MIT）/Marker（Apache）+ GROBID（Apache）取元数据；OCR 用 PaddleOCR/Surya（Apache）；问答 RAG 用 PaperQA2（Apache）；**避开 PyMuPDF/Nougat 权重/AGPL 组合以免许可传染**；双语 PDF 翻译若参考 PDFMathTranslate 需接受 AGPL 或自研等价管线。

---

## 待确认问题

1. **厂商主体**：任务书中的「上海阅知信息科技」在官方协议/商店页中未出现；官方主体为上海亦答网络科技有限公司（坚果云）与 Astronet Technology PTE LTD（新加坡）。两者股权/分工关系、以及 Microsoft Store 条目上显示为深圳某第三方实体的授权关系待确认。
2. **桌面端真正的 AI/翻译调用链**：LLM 与翻译引擎供应商完全未披露（"自研"口径无法验证）。是否存在自研模型、是否调用第三方 API、是否使用境内合规大模型，均未知。
3. **月付套餐**：官网套餐文案存在「月付专业版」，但支付宝接口的 `pays` 列表未列出月付商品；月付是否在售、价格多少未验证。
4. **退款政策冲突**：前端「7 天无理由退款」vs 购买协议「开通后不可退款」，实际执行口径未验证。
5. **朗读/TTS、桌面宠物的真实形态**：前端存在 `desktopPet` 设置项，但未找到任何功能文档、截图或用户提及；「朗读」功能在全部官方材料中无证据，判定为不存在（待官网 UI 复核）。
6. **术语库/glossary**：未发现用户可维护的术语表；只有 "AI 术语解释"。是否存在隐藏的专业词库设置未验证。
7. **离线能力边界**：官方称「常用文献本地缓存支持离线阅读」，但离线能否翻译/笔记/高亮同步，未验证。
8. **Zotero 独立插件**：历史帮助文档提到在 Zotero 中安装 Scholaread 插件；当前文档只描述「客户端读取本地 Zotero 数据库」+「Zotero 阅读助手」，是否存在可下载的 `.xpi`、其仓库与许可，未验证。
9. **`mobile-agent` 资源包**（v1.0.6 zip）的作用：是端侧 Agent 运行时还是仅提示词/工具配置，未验证。
10. **「连接至 OpenAI / 集成密钥」**：形态（MCP 连接器？ChatGPT 应用？）、权限范围与数据出境情况未验证。
11. **重排页数/文件大小硬上限的具体数值**（前端为变量 `{max_page}`/`{max_size}`），未取到具体数字。
12. **SciSpace/ChatPDF/ReadPaper 的完整最新定价与功能对比**：本次仅取到公开定价页与自述；ChatPDF 未取到 Plus 具体价格，ReadPaper 的付费档位未取到。
13. **浏览器扩展架构**：MV2/MV3、是否开源、是否与桌面客户端通信，未验证。
14. **是否存在任何官方开源组件或许可声明页**（Electron 应用的 third-party licenses）——本次未在公开网页找到；若需彻底确认，应解析已安装客户端内的 `LICENSES` 资源（另一路调查已有 `research/asar/` 产物可复用）。

---

### 附：本次一手抓取记录（便于复核）

- 官方帮助中心全量页面：`https://www.scholaread.cn/help/sitemaps.xml` → 48 个页面（pc-faq-1..17、app-faq-1..7、web-faq-1..8、agent/scenario/boundary/result-check/key-concepts/getting-started、privacy/terms/purchase-agreement/acknowledgment/about/nutstore-bundle-purchase-faq/baidu-scholaread）。
- 官方英文帮助中心：`https://www.scholaread.com/help`（含 Citation Assistant、Privacy、Terms、Purchase Agreement）。
- 官方公开接口：`/api/configs/version`、`/api/configs`、`/api/configs/pricing_account_state_rights`、`/api/pay/configs?...`（价格与额度均取自此处）。
- 发布通道：`https://cdn.scholaread.cn/assets/pc-releases/1.1.86/cn/latest{,-mac,-linux}.yml`（Electron/electron-updater 证据 + 安装包 URL/大小）。
- 商店元数据：iTunes Lookup API（CN/US）、iTunes 评论 RSS（CN 两页 + US）、Google Play 页面、Chrome Web Store 页面、Microsoft Store 页面与商店接口。
- 第三方：appinn 开发者自荐帖两篇（含完整功能自述）、苹果/谷歌商店用户评论、黑猫投诉（搜索快照）。
- 开源数据：GitHub REST API（repos/releases/search）+ 各仓库 LICENSE 原文。
