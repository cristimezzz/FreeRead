# 09 · 获取与合规规范（Fetch & Compliance）· **合规红线**

> 状态：**冻结**。本文件是 FreeRead 的**合规红线文档**，优先级高于任何功能需求；与之冲突的实现一律回退。
> 上游依据：[`plan §1.2 不做清单`](../plan/FreeRead-技术方案与里程碑.md)、[`plan §4.4 合规内建`](../plan/FreeRead-技术方案与里程碑.md)、[`plan §7 R5`](../plan/FreeRead-技术方案与里程碑.md)、[`report §8 合规观察`](../report/Scholaread-调研报告.md)（反面对照：hardcode Sci-Hub、机构代理、DOI→`/pdfdirect/` 改写）。
> 术语：`NetGuard`、`FetchProvider`、`docId`、`OpLogEntry` 以 [`README.md §3`](./README.md) 为准。
> 责任包：`packages/fetch`（获取器）+ `packages/zotero`（只读适配器）；**全仓所有出站请求必须经 `NetGuard`**，违反即 F2；出现 Sci-Hub/付费墙绕过即 F3。

## 1. 原则声明（必须先于代码存在）

FreeRead **只通过以下两种途径**获取文献与元数据：① **开放获取（OA）**——arXiv、PMC OA subset、Unpaywall 指向的合法 OA 副本、Crossref/OpenAlex 的公开元数据；② **用户自有授权会话**——用户在自己的机器、用自己的账号/校园网权限在内嵌浏览器中访问来源站点并下载（FreeRead 只做"发起导航 + 保存到本地"，不代持/不重放凭据、不代填登录表单）。

**明确禁止**（任何一条都构成发布阻断）：

| # | 禁止 |
|---|---|
| C1 | 规避付费墙、DRM、验证码、机构认证或任何访问控制（含"让用户手动登录后自动继续抓取"的自动化链路） |
| C2 | 内置、引用或提示任何 Sci-Hub / LibGen / Z-Library / Anna's Archive 类站点（域名、伪协议、镜像列表、URL 模板） |
| C3 | 用标题/DOI 拼接第三方检索或代理站点链接（如 `scholar.google.*/scholar?q=<title>`、`/doi/epdf/` → `/pdfdirect/` 改写、`sci-hub://<title>` 伪协议） |
| C4 | 批量抓取（爬虫式遍历目录/检索页）、绕过来源方速率限制、伪造 User-Agent 冒充浏览器或他人 |
| C5 | 上传用户文献全文到任何第三方；把用户凭据写入 `config.json`、日志或审计文件 |
| C6 | 修改用户 Zotero 库（`zotero.sqlite` 一律只读副本，见 §7） |

**声明义务（实现与发布都必须满足）**

| 位置 | 内容（i18n 或静态文本） |
|---|---|
| `README.md` 顶部 | "FreeRead 只通过**开放获取（OA）**与**用户自有授权会话**获取文献；不提供、也不会提供任何付费墙绕过能力。请遵守来源方服务条款与所在机构规定。" |
| 首次启动引导（`onboarding.compliance`） | 同文 + 三条要点：① 下载文件只保存在本地；② 不向 FreeRead 项目方上传任何内容（本项目不设服务器）；③ 使用学术资源须遵守来源方 ToS 与订阅协议 |
| 设置页「合规与网络」 | 白名单可查看、审计日志可查看/导出（§6）、"禁止清单"只读展示（不可由用户关闭） |

## 2. `NetGuard` 规范（唯一出站入口）

### 2.1 接口

```ts
// packages/fetch/src/net-guard.ts
export type NetPurpose = 'oa-metadata' | 'oa-fulltext' | 'llm' | 'asset' | 'user-browser';
export interface NetContext {
  purpose: NetPurpose;
  providerId: string;      // 'arxiv' | 'pmc' | 'unpaywall' | 'openalex' | 'crossref' | 'ollama' | ...
  docId?: string;          // 关联文档（可空）
  allowLocal?: boolean;    // 仅本地 Provider（ollama / 本地 vLLM）可为 true，见 §2.4
  maxRedirects?: number;   // 默认 3，硬上限 3
}
export interface NetGuard {
  /** 唯一允许发起网络请求的方法；白名单/协议/解析/重定向/审计全在此实现 */
  request(url: string, init: RequestInit, ctx: NetContext): Promise<Response>;
  /** 供设置页与"用户显式配置 LLM"流程使用；违规抛 AppError，不发起请求 */
  assertAllowed(url: string, ctx: NetContext): void;
  readonly whitelist: readonly WhitelistEntry[];
}
export interface WhitelistEntry {
  host: string;            // 精确主机小写，如 'export.arxiv.org'
  allowSubdomains: boolean;
  purposes: NetPurpose[];  // 该主机允许的用途
  source: 'builtin' | 'user-llm';   // user-llm 条目每会话确认，见 §2.2
}
```

**实现约束**：`packages/fetch` 与 `packages/translate` **不得** import `node:http`/`node:https`/`axios`/`got`/`node-fetch`；只允许 `NetGuard` 内部使用 `undici` 的 `fetch`。CI 有 grep 门禁（§3.3）。

`purpose: 'user-browser'` 的导航不受 `undici` 承载（由 Electron 会话网络栈发出），因此该用途下 `NetGuard` 负责**出站前校验**（黑名单 → 白名单 → 协议 → DNS，全量执行），并在 Session 分区上以 `session.webRequest.onBeforeRequest` **镜像同一套规则**拦截子请求（黑名单与 `http://` 一律阻断；非白名单子域仅告警不阻断，避免破坏出版商页面自身的静态资源），cookie 由 Chromium 会话管理、FreeRead 代码不读取。

### 2.2 域名白名单表（内置，硬编码）

| `host` | 允许子域 | 用途 | 说明 |
|---|---|---|---|
| `arxiv.org` | ✅ | `oa-metadata`, `oa-fulltext` | Atom API、摘要页 |
| `export.arxiv.org` | ✅ | `oa-metadata`, `oa-fulltext` | `/api/query`、`/pdf/{id}` |
| `ncbi.nlm.nih.gov` | ✅ | `oa-metadata`, `oa-fulltext` | PMC 页面；子域规则覆盖 `www` |
| `eutils.ncbi.nlm.nih.gov` | ✅ | `oa-metadata` | E-utilities（含 OA subset 判定） |
| `api.crossref.org` | ❌ | `oa-metadata` | 仅元数据 |
| `api.openalex.org` | ❌ | `oa-metadata` | 仅元数据 |
| `api.unpaywall.org` | ❌ | `oa-metadata` | 需 `email` 参数，见 §4.3 |
| `cdn.jsdelivr.net` | ✅ | `asset` | 仅模型/词库/字体等静态资源（校验 SHA256 后落盘） |
| 用户配置的 LLM `baseUrl` | ❌（按用户输入精确匹配） | `llm` | 动态条目 `source: 'user-llm'`，**每会话首次使用前弹确认**；变更 `baseUrl` 需重新确认 |
| `127.0.0.1` / `localhost` | ❌ | `llm` | 本地 Provider 专用，仅当 `ctx.allowLocal === true`；`http://` 在此唯一合法（§2.4） |

### 2.3 白名单匹配规则（可机检）

1. **规范化**：URL 先 `new URL()` 解析；`hostname` 转小写 ASCII（IDN 走 `domainToASCII`）；端口为协议默认值时归一化；路径不做归一化但参与审计；
2. **主机匹配**：`hostname === entry.host`，或 `entry.allowSubdomains && hostname.endsWith('.' + entry.host)`；
3. **禁止通配 TLD**：白名单条目不得为 `*.com`、`*.org`、`*.io`、`*.cn` 等公共后缀；新增条目必须通过公共后缀检查（`tldts`，MIT）；构建期校验（单测 T9），**不通过即构建失败**（不引入新错误码）；
4. **禁止 IP 直连**：`hostname` 为 IPv4/IPv6 字面量**一律拒绝** → `FR-NET-006 reason='ip_literal'`（唯一例外：`ctx.allowLocal === true` 且地址 ∈ `{127.0.0.1, ::1}`）；
5. **重定向**：每跳都重新执行 §2.3.2 与 §2.4；**最多 3 跳**，超限抛 `FR-NET-003`（`reason='allowlist'`）；跨域重定向（`hostname` 变化）必须重新校验，未命中白名单即中断并抛 `FR-NET-003`（`reason='allowlist'`）；
6. **方法限制**：`user-browser` 之外的用途只允许 `GET`/`POST`；`oa-*` 用途一律 `GET`（Crossref/OpenAlex 亦为 GET）；
7. **头白名单**：仅允许 `accept`、`accept-language`、`content-type`、`user-agent`、`authorization`（仅 `llm` 用途）、`x-api-key`（仅 `llm`）；其余头一律剔除（含 `cookie`、`referer`、`origin`）；
8. **体积上限**：单次响应 ≤ 200 MB（PDF）；`asset` 用途 ≤ 50 MB；超限中断并抛 `FR-NET-003`（`reason='size_exceeded'`）；
9. **用户点击例外**：`fr:app:openExternal` 以 `reason='user-click'` + `confirmedByUser:true` 传入的 https URL 可放行任意主机，但**必须先弹确认框**、**必写审计**并回传 `whitelisted:false`（`06-ipc-contract.md` N3）；未确认 → `FR-NET-003 reason='user_click_unconfirmed'`；**黑名单（§3.1）优先于此例外**，命中即 `reason='denylist'`。

### 2.4 协议与 DNS 解析校验

| 规则 | 规定 |
|---|---|
| 协议 | **`http://` 一律拒绝** → `FR-NET-002 reason='http_forbidden'`；唯一例外：`ctx.allowLocal === true` 且 `hostname ∈ {127.0.0.1, ::1, localhost}`（Ollama / 本地 vLLM） |
| DNS 解析 | 请求前解析**全部** A/AAAA 记录，逐条校验；任一为私网/回环/链路本地/保留地址 → `FR-NET-006 reason='ssrf_private'`，**不发起连接** |
| 拒绝的网段 | IPv4：`10/8`、`172.16/12`、`192.168/16`、`127/8`、`169.254/16`、`0/8`、`100.64/10`、`192.0.0/24`、`198.18/15`、`224/4`、`240/4`；IPv6：`::1`、`fc00::/7`、`fe80::/10`、`::ffff:0:0/96` 内的私网映射、`2001:db8::/32`、组播 |
| 例外与实现 | `ctx.allowLocal === true` 时允许 `127.0.0.1`/`::1`，**仍禁止**其它私网段与其他主机名；用 `node:dns` 的 `resolve4/resolve6`，网段表硬编码于 `packages/fetch/src/net/private-ranges.ts`（可枚举前缀表 + 单测，**禁止**运行时位运算算术） |

### 2.5 与抓取相关的速率限制（硬编码）

| 来源 | 上限 | 依据 |
|---|---|---|
| arXiv | **1 req / 3 s**，单次运行 ≤ 2000 请求 | arXiv API ToS：建议 3 秒间隔、批量查询 |
| NCBI E-utilities | 无 API key：**3 req / s**；有 key：10 req / s（`tool` + `email` 必填） | NCBI Usage Guidelines |
| Unpaywall | **10 req / s**，`email` 必填 | Unpaywall API 条款 |
| OpenAlex / Crossref | OpenAlex **10 req / s**、Crossref **5 req / s**，`mailto` 必填 | OpenAlex polite pool / Crossref REST API etiquette |
| `cdn.jsdelivr` | **2 req / s**（资源下载） | 公共 CDN 礼貌使用 |
| 本地 LLM | 不限速，仅并发 1（`08-translation.md` §3.1） | 本机资源 |

- **User-Agent 规范**：`FreeRead/<version> (+https://github.com/<org>/freeread; mailto:<user-email>)`；`<user-email>` 由用户在设置页填写（用于 NCBI/Unpaywall/OpenAlex/Crossref 的礼貌池），**未填写时上述四个来源不可用**（UI 提示"需填写联系邮箱"）；**禁止**伪造浏览器 UA、禁止轮换 UA 规避限制。限速器为进程内令牌桶，跨 Provider 独立。

### 2.6 错误码（语义以 [`11-error-handling.md`](./11-error-handling.md) §3 为权威）

`FR-NET-001..003` 与 11 §3 同名同义；细类用 `details.reason` 枚举区分（与 `06-ipc-contract.md` §5.4 对 `FR-IPC-002` 的做法一致）。**`FR-NET-003` 是全部合规拦截的统一码**（白名单未命中与黑名单命中都是"请求不在允许的来源范围内"），靠 `reason` 区分以便审计与测试。

| 码 | `reason` | 触发 | 11 §3 语义 | 可重试（11 §4） |
|---|---|---|---|---|
| `FR-NET-001` | — | 离线（`navigator.onLine === false` 或探测失败） | 离线 | 是 |
| `FR-NET-002` | — | `ENOTFOUND`/`ECONNREFUSED`（DNS/连接失败） | DNS/连接失败 | 是 |
| `FR-NET-002` | `http_forbidden` | 非本地 Provider 使用 `http://` | 同上（拒绝发生在连接层，未建连） | **否** |
| `FR-NET-002` | `scheme_forbidden` | `file:`/`data:`/`javascript:`/`blob:` | 同上 | **否** |
| `FR-NET-003` | `allowlist` | 主机未命中白名单（含重定向后的目标主机） | 合规拦截 | **否**（fatal） |
| `FR-NET-003` | `denylist` | **命中禁止清单**（§3.1） | 同上 | **否，永不重试**（且记 `error` 审计） |
| `FR-NET-003` | `user_click_unconfirmed` | `user-click` 放行但用户未确认（§2.3 规则 9） | 同上 | 否 |
| `FR-NET-004` | — | TLS/证书校验失败 | 证书/TLS 失败 | 否 |
| `FR-NET-005` | — | 更新源不可达或返回非法（`fr:app:checkUpdate`） | 更新检查失败 | 是 |
| `FR-NET-006` | `ssrf_private` / `ip_literal` | DNS 解析到非公网地址（私网/回环/链路本地/保留）或 `hostname` 为 IP 字面量（本地 Provider 回环例外之外） | **本规范新增** | 否 |
| `FR-NET-006` | `audit_unavailable` | 审计写盘失败 → **拒绝该请求**（审计不可用则不出站） | **本规范新增** | 否（修好磁盘后重发） |

> 重定向 > 3 跳：抛 `FR-NET-003`（`reason='allowlist'`，`details.hops`）+ 审计记 `policy:'deny'`——因为此时**必然**存在未命中白名单的目标；纯白名单链超跳数属实现缺陷，由单测 T7 覆盖。

## 3. 黑名单（硬编码禁止 + CI 门禁）

### 3.1 禁止清单（匹配即抛 `FR-NET-003` + `details.reason='denylist'`）

| 模式（大小写不敏感，匹配主机名） | 说明 |
|---|---|
| `sci-hub.*`、`*.sci-hub.*`、`scihub.*`、`*.scihub.*`、`sci-hub.se/.st/.ru/.ee` | Sci-Hub 及已知镜像 |
| `libgen.*`、`*.libgen.*`、`libgenesis.*` | LibGen |
| `z-lib.*`、`*.z-lib.*`、`zlib.*`、`zlibrary.*`、`*.zlibrary.*` | Z-Library |
| `annas-archive.*`、`*.annas-archive.*` | Anna's Archive |
| `booksc.*`、`bookfi.*`、`ebookee.*`、`freebookspot.*` | 同类影子图书馆 |

匹配实现：`packages/fetch/src/net/blocklist.ts` 内置**域名后缀表**（非正则全 URL），匹配函数对 `hostname` 做后缀判定；`NetGuard` 在**任何其他校验之前**先查黑名单（黑名单优先级最高，包括 `user-browser` 用途与用户手输 URL）。

### 3.2 禁止的行为模式（代码评审要点，CI 亦检查）

1. 用标题/DOI 拼接第三方检索或代理链接（`scholar.google.*?q=`、`/sci-hub/`、`sci-hub://`）；
2. DOI → 出版商 PDF 直链改写（`/doi/epdf/` → `/pdfdirect/`、`/doi/pdf/` 猜测）；
3. "用户登录后自动继续"的抓取状态机（等待登录/验证码后自动重试下载）；
4. 代理/镜像列表、`config_allow_download_from_*` 式开关；
5. 通用"标题 → 任意站点全文"搜索—下载流水线（只允许 §4 的具名 Provider 与用户会话）。

### 3.3 CI 门禁：`scripts/forbid-domains.sh`

```bash
#!/usr/bin/env bash
# pnpm forbid 的一部分：禁止域名/关键词 grep 门禁（README F3、plan §6.3）
set -euo pipefail
PATTERNS='sci-?hub|libgen|z-?lib(rary)?|annas-archive|booksc|bookfi|\bebookee\b|scholar\.google|pdfdirect|epdf|institution(al)?[-_ ]?proxy|ezproxy'
# 只扫源码与配置；specs/**（必须能描述红线）、docs/adr/**、THIRD_PARTY_NOTICES.md 由 CI 参数排除
grep -rInE "$PATTERNS" --include='*.ts' --include='*.tsx' --include='*.js' --include='*.json' \
  --include='*.py' --include='*.html' --include='*.sh' --exclude-dir=specs apps packages services scripts .github \
  && { echo "FAIL: 命中禁止域名/关键词（见 specs/09-fetch-compliance.md §3）"; exit 1; } \
  || echo "OK: 未命中禁止域名/关键词"
```

- 排除项**仅限**：`specs/**`、`docs/adr/**`、`THIRD_PARTY_NOTICES.md`、测试夹具中的**显式反例**（须带 `// forbid-allow: <理由>` 同行注释，评审重点检查）；
- CI 步骤：`pnpm forbid`（`00-conventions.md` §7 已列），未通过直接阻断合并；新增任何"疑似"字符串必须在 PR 描述中说明用途，否则视为 F3。

## 4. `FetchProvider` 列表与协议

```ts
// packages/fetch/src/provider.ts
export interface FetchContext {
  signal: AbortSignal;
  userEmail: string;                 // 必填（礼貌池）；缺失时相关 Provider 抛 FR-FETCH-004 reason='missing_email'
  docId?: string;
  onProgress?: (ratio: number) => void;
}
export interface OaLocation {
  url: string;                       // 必须是 https
  host: string;                      // 展示给用户，用于"需用户会话"提示
  license?: string;                  // 如 'CC-BY-4.0'
  version?: 'published' | 'accepted' | 'submitted' | 'unknown';
}
export interface FetchMetadata {
  doi?: string; arxivId?: string; pmcid?: string;
  title?: string; authors?: string[]; year?: number; venue?: string; abstract?: string; license?: string;
  sourceId: FetchProviderId;         // 该字段的来源（用于 §5.3 优先级）
  confidence: number;                // 0..1，来源自带或按 §5.2 计算
  isOa?: boolean;
  oaLocations?: OaLocation[];
}
export type FetchProviderId = 'arxiv' | 'pmc' | 'unpaywall' | 'openalex' | 'crossref' | 'user-session';
export interface FetchProvider {
  readonly id: FetchProviderId;
  readonly displayName: string;
  /** 只读元数据；不下载全文 */
  lookup(query: { doi?: string; arxivId?: string; title?: string }, ctx: FetchContext): Promise<FetchMetadata | null>;
  /** 把合法 OA 副本写入 library 暂存目录；失败不得留下半成品 */
  download(meta: FetchMetadata, outDir: string, ctx: FetchContext): Promise<{ pdfPath: string; contentType: 'application/pdf'; bytes: number }>;
}
```

### 4.0 失败错误码（`FR-FETCH-xxx`，语义以 [`11-error-handling.md`](./11-error-handling.md) §3 为权威，本表只补"在本模块的具体触发"）

| 码 | 11 §3 含义 | 本模块触发 | 可重试（11 §4） |
|---|---|---|---|
| `FR-FETCH-001` | 无 OA 版本 | `is_oa === false` 或 OA subset 判定失败 → **强制**转为 `outcome='needs-user-session'` 提示，**不得**回退到任何其它来源 | 否 |
| `FR-FETCH-002` | 来源限流 | HTTP 429/503；或本地限速器排队（`details.reason='local_throttle'`） | 是（按 `Retry-After`，≤ 2 次） |
| `FR-FETCH-003` | DOI 非法 | `normalizeDoi`/`normalizeArxivId` 校验失败（§5.1）；未找到用 `reason='not_found'` 区分（§4.1） | 否 |
| `FR-FETCH-004` | 元数据补全失败 | Provider 返回空或超时；缺必填 `userEmail`/`mailto`（`reason='missing_email'`）；元数据冲突无法判定（`reason='metadata_conflict'`）→ 一律保留已有信息，**不阻塞导入** | 是（用户确认后） |
| `FR-FETCH-005` | 引文格式不支持 | CSL 导出请求了未实现的样式（**与文献获取无关**，本文不改其语义） | 否 |
| `FR-FETCH-006` | 下载内容非法（**09 新增，待 11 登记**） | `content-type` 或 `%PDF-` 魔数校验失败 | 否 |
| `FR-FETCH-007` | 体积超限（**09 新增，待 11 登记**） | 单次响应超 §2.3.8 上限；`ENOSPC` 归 `FR-STORE-001` | 否 |
| `FR-FETCH-008` | 元数据冲突待确认（**09 新增，待 11 登记**） | §5.3 无法自动决策：保留已有值 + 标"待确认"，**不阻塞导入** | 否 |

> **"无 OA"的语义是硬性的**：`FR-FETCH-001` 时唯一允许的动作是提示用户自行通过授权渠道获取（可打开内嵌浏览器由用户操作），**禁止**任何形式的自动回退尝试。用户取消会话 → 返回 `outcome='canceled'`（**不是错误**，不记 `error` 级日志）。
> 上游被 `NetGuard` 拒绝时**透传** `FR-NET-00x`，不包装成 `FR-FETCH-*`。
> 落盘失败复用存储域既有码：权限 → `FR-STORE-002`；空间 → `FR-STORE-001`；库写入 → `FR-LIB-002/005`。

### 4.1 `arxiv`

| 项 | 规定 |
|---|---|
| 输入 | `arxivId`（优先）、`doi`（`10.48550/arXiv.<id>`）、`title`（走 `search_query=ti:"..."`） |
| 元数据 URL | `https://export.arxiv.org/api/query?id_list={id}`（Atom）或 `?search_query=ti:%22{title}%22&max_results=5` |
| 全文 URL | `https://arxiv.org/pdf/{id}`（**不带版本号时取最新版**）；旧式 ID `cmp-lg/9701001` 原样拼入 |
| 速率 | 1 req / 3 s；`User-Agent` 按 §2.5 |
| 映射 → `meta.json` | `title` ← `<entry><title>`（去换行折叠空白）；`authors` ← 全部 `<author><name>`；`year` ← `<published>` 年份；`venue` ← `arXiv preprint arXiv:{id}`；`abstract` ← `<summary>`；`doi` ← `<arxiv:doi>`（缺失用 `10.48550/arXiv.{id}`）；`license` ← `<link rel="license">`；`isOa = true` |
| 落盘与失败 | `paper.pdf` 写入暂存区并校验 `%PDF-` 魔数 + 体积；未找到 → `FR-FETCH-003 reason='not_found'`；限流 → `FR-FETCH-002` |

### 4.2 `pmc`（PMC OA subset）

| 项 | 规定 |
|---|---|
| 输入 | `pmcid`（`PMC\d+`）、`doi`、`title` |
| OA 判定 | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pmc&term={doi}[DOI]&tool=freeread&email={email}` → 取 `PMCID`；再 `efetch.fcgi?db=pmc&id={pmcid}&retmode=xml`，仅当返回 `<article>` 带 OA 许可标签（`<license>` 非空且 `license-type` 为 CC 系）才视为 OA subset |
| 全文 URL | `https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/`（页面内 PDF 链接由 `efetch` 的 `<self-uri>`/`<uri>` 提供，**不做站点爬取**） |
| 速率 | 无 key 3 req/s，有 key 10 req/s；`tool=freeread&email=…` 必填（缺 → `FR-FETCH-004 reason='missing_email'`） |
| 映射 | `title` ← `<article-title>`；`authors` ← `<contrib contrib-type="author"><name>`；`year` ← `<pub-date>`；`venue` ← `<journal-title>`；`abstract` ← `<abstract>`；`doi` ← `<article-id pub-id-type="doi">`；`pmcid` ← `<article-id pub-id-type="pmc">`；`license` ← `<license>`；`isOa` 由 OA 判定得出；非 OA subset → `FR-FETCH-001`（提示"该文不在 PMC 开放获取子集，请通过授权渠道获取"） |

### 4.3 `unpaywall`

| 项 | 规定 |
|---|---|
| 输入与 URL | `doi`（**必需**，无 DOI → `FR-FETCH-003`）；`https://api.unpaywall.org/v2/{doi}?email={userEmail}`（`email` 必填，缺 → `FR-FETCH-004 reason='missing_email'`） |
| 速率 | 10 req/s |
| 映射 | `is_oa` → `isOa`；`best_oa_location` → `oaLocations[0]`（`url_for_pdf` 优先，回退 `url`）；`license` ← `best_oa_location.license`；`version` ← `version`；`title/year/journal_name/authors` 仅补齐空字段 |
| 关键约束 | **只使用返回的 OA 直链**；非 https 或非白名单主机的 `oaLocations` **不得**下载（除 `user-session` 外不允许下载出版商站点）——此时 UI 显示"OA 副本位于 `<host>`，请用内嵌浏览器自行下载" |
| 失败 | 无记录 → `FR-FETCH-003 reason='not_found'`；`is_oa === false` → `FR-FETCH-001` + `outcome='needs-user-session'` |

### 4.4 `openalex` / 4.5 `crossref`（**仅元数据**）

| 项 | `openalex` | `crossref` |
|---|---|---|
| URL | `https://api.openalex.org/works/doi:{doi}`；标题检索 `/works?search={title}&per-page=5&mailto={email}` | `https://api.crossref.org/works/{doi}`；标题检索 `/works?query.bibliographic=…&rows=5&mailto={email}` |
| 速率 | 10 req/s；`mailto` 必填 | 5 req/s；`mailto` 必填 |
| 映射 | `display_name`→`title`；`publication_year`→`year`；`authorships[].author.display_name`→`authors`；`primary_location.source.display_name`→`venue`；`abstract_inverted_index` **本地重建**为 `abstract`（不额外请求）；`best_oa_location.pdf_url`→`oaLocations`（受 §4.3 约束）；`ids.doi`→`doi` | `title[0]`→`title`；`issued.date-parts[0][0]`→`year`；`author[]`（`given`+`family`）→`authors`；`container-title[0]`→`venue`；`abstract`（JATS 去标签取纯文本）→`abstract`；`license[].URL`→`license`；`DOI`→`doi` |
| 限制 | **不下载全文**；`download()` 抛 `FR-FETCH-001`（该 Provider 无全文能力） | 同左 |

### 4.6 `user-session`（用户自有授权会话）

| 项 | 规定 |
|---|---|
| 触发 | ① `FR-FETCH-001` 提示中的"打开浏览器"；② 用户在地址栏/文献详情页手输 URL |
| 流程 | `NetGuard.request(url, init, { purpose: 'user-browser', providerId: 'user-session' })` 仅**放行首次导航**（黑名单、`http://` 与 §2.4 仍生效）；页面在**独立 session 分区**（Electron `partition: 'persist:user-browser'`）中加载，cookie 由 Chromium 自行管理，**FreeRead 代码不读取 cookie** |
| 下载落盘 | 仅当用户点击"保存到文献库"时，把当前响应字节流写入 `library/<citekey>/paper.pdf`；文件名由用户确认；校验 `%PDF-` 魔数（否则 `FR-FETCH-006`） |
| 禁止 | ❌ 代填/代持凭据；❌ 读取或导出 cookie/localStorage；❌ 缓存网页内容（HTML/JS/CSS 一律不落盘，仅内存会话）；❌ 后台自动连续下载多篇（每次须用户显式触发）；❌ 上传任何内容 |
| 审计与失败 | 每次导航记 `purpose: 'user-browser'`（§6），`query` 全量脱敏为 `?…`；用户取消/超时 → 返回 `outcome='canceled'`（不是错误码） |

## 5. 元数据解析与冲突

### 5.1 归一化

```ts
// DOI：小写前缀，保留注册者/后缀大小写；去 https://doi.org/、doi:、末尾标点；允许 ()[]<>;: 与 unicode
normalizeDoi(raw: string): string   // 校验 /^10\.\d{4,9}\/[-._;()/:a-z0-9]+$/i，失败 → FR-FETCH-003
// arXiv：'arXiv:2301.12345v2' | 'https://arxiv.org/abs/2301.12345v2' | '2301.12345' → '2301.12345'
//        'cmp-lg/9701001' → 'cmp-lg/9701001'（旧式：先取 '/' 前归档名，再取 YYMMNNN）
//        版本号 vN 在比较时忽略，下载时保留输入版本（缺省取最新版）
normalizeArxivId(raw: string): string
canonicalId = doi ? `doi:${normalizeDoi(doi)}` : `arxiv:${normalizeArxivId(arxivId)}`   // 去重主键
```

> 去重说明（与 `05-storage.md` 一致）：`docId = sha256(pdf 字节)`，同一篇文章的**不同 OA 副本会产生不同 `docId`**；导入时若 `canonicalId` 相同，写入 `meta.json` 的 `duplicateOf: <docId>` 并提示用户，**不自动合并**。

### 5.2 标题模糊匹配

```
normalizeTitle(t): 小写 → 去变音符号 → 去标点 → 折叠空白 → 去首位 "the/a/an" → token 数组
similarity(a, b):
  1. normalizeTitle 后完全相等 → 1.0
  2. seq = 2 * sum(|matching_blocks|) / (len(a) + len(b))    # difflib.SequenceMatcher 同义实现
  3. 门控（任一不满足 → 0.0）：a. 首作者姓氏（casefold）相同，或两方均无作者信息；
     b. 年份差 ≤ 1（两方均无年份时跳过此门控）
  4. 返回 seq
判定阈值：>= 0.75 → 同一文献（写入 provenance，见 §5.3）；0.60–0.75 → 标 low-confidence，UI 要求确认；< 0.60 → 拒绝
```

> 阈值 0.75 与 [`plan §6`](../plan/FreeRead-技术方案与里程碑.md) 的标题匹配思路一致（调研报告 §7.3/§9.1 的元数据来源组合）。

### 5.3 冲突优先级与 provenance

优先级（高 → 低）：**用户手填 > `crossref` > `openalex` > `arxiv`/`pmc` 的抓取结果**。

| 规则 | 规定 |
|---|---|
| 字段级合并 | 逐字段取最高优先级来源的非空值；不得因低优先级来源覆盖已有高优先级值 |
| 用户锁定 | `meta.json` 中用户手填字段写 `"userEdited": ["title","year"]`；这些字段**永不被**任何 Provider 覆盖 |
| 记录来源 | `meta.json` 增加 `provenance: { title: 'crossref', year: 'user', … }`（取值 = `FetchProviderId` 或 `'user'`） |
| 冲突标记 | 同一字段两来源相似度 ≥ 0.75 但值不同 → 保留高优先级值，低优先级值写入 `provenanceConflicts[]` 供详情页对比；无法判定 → `FR-FETCH-008`（保留已有值 + 标"待确认"，**不阻塞导入**） |
| `citekey` | 首次生成后**冻结**（`firstauthorYEARword`）；后续元数据修正只更新 `meta.json`，**不得**重命名目录（保护 `annotations.jsonl` 与笔记） |

## 6. 审计日志

- 文件：`%APPDATA%/FreeRead/logs/net-audit.jsonl`（仅本地；**不上传**，不与 `app-*.log` 混合）；每次出站请求写一行（**含被拒绝的请求**），格式：

```json
{"at":1759420000123,"provider":"unpaywall","url_host":"api.unpaywall.org","status":200,"bytes":18432,"purpose":"oa-metadata","doc_id":"a1b2…","method":"GET","path":"/v2/10.1000/xyz","redirects":0,"policy":"allow"}
```

| 字段 | 规定 |
|---|---|
| `at` | UTC 毫秒（`00-conventions.md` §2.5）；`provider`/`url_host`/`status`/`bytes`/`purpose` 必需，`doc_id` 可空 |
| `url_host` / `path` | **不记完整 URL**：`url_host` 只记主机；`path` 仅白名单 OA 来源记录，`purpose === 'llm'` 或 `'user-browser'` 时统一记为 `/…`（全脱敏） |
| **脱敏（强制）** | 不记录 query 中的邮箱/token/key：`email`/`mailto`/`api_key`/`token`/`authorization`/`cookie` 等参数值一律替换为 `[REDACTED]`；写入前过 `redactAuditLine()`，单测断言"输入含 `email=x@y.com` 的输出不含 `x@y.com`" |
| 被拒请求 | `policy: 'deny'` + `status: 0` + `reason: 'FR-NET-00x'`；黑名单命中额外写 app 日志 `error 'net.blocked'` |
| 保留与容量 | **30 天**（每日轮转 `net-audit-YYYY-MM-DD.jsonl`，`winston-daily-rotate-file`）；上限 50 MB，超限先删最旧 |
| 用户可见 | 设置页「合规与网络 → 出站审计」倒序展示（host/时间/用途/结果），支持导出 JSON/CSV 与"清空审计日志" |
| 与 `OpLogEntry` 的关系 | 审计日志**不**写入 `op_log`（后者是用户操作与撤销日志）；两者互不引用，避免撤销操作影响审计完整性 |

## 7. Zotero 只读集成

| 规则 | 规定 |
|---|---|
| 源库与打开方式 | 源库 `~/Zotero/zotero.sqlite`（路径可配置）；**必须先复制到副本** `%APPDATA%/FreeRead/cache/zotero/zotero-<ts>.sqlite`，再以 `readonly: true` 打开副本；**禁止**直接打开用户库 |
| 复制前检查 | 若存在 `zotero.sqlite-wal`，先复制 `-wal` 与 `-shm` 再复制主库（保证一致性）；库被锁时用 `better-sqlite3` 的 `backup()` API 生成副本 |
| 禁止事项 | ❌ 任何 `INSERT/UPDATE/DELETE/ATTACH/VACUUM`（连接启动即 `PRAGMA query_only = 1`）；❌ 写 `zotero.sqlite` 或 Zotero 数据目录任何文件；❌ 修改 Zotero 配置/注册表；❌ 联网同步用户库 |
| 读取范围 | 仅 `itemTypes`/`items`/`itemData`/`itemDataValues`/`creators`/`itemCreators`/`collections`/`collectionItems`/`itemAttachments` 等元数据表；**不读** `fulltextWords`/`fulltextItemWords`（体积大且无必要） |
| 字段映射与导入 | `creators`（`firstName`+`lastName`）→`authors`、`date`→`year`、`publicationTitle`→`venue`、`DOI`→`doi`、`abstractNote`→`abstract`、`itemAttachments.path`→本地 PDF 路径（`storage:` 前缀解析到 Zotero `storage/`）；只**读取**副本并复制 PDF 到 FreeRead 知识库，导入不得触发任何来源方请求（除用户另行选择"补全元数据"） |
| 测试断言（必须） | `packages/zotero/src/**/*.test.ts`：对 fixture 库导入后断言原文件 `sha256` 与 `mtime` **均未变化**；断言连接为只读（写操作抛错）；断言不产生 `-wal`/`-shm` 新文件 |

## 8. 合规测试与评审流程

### 8.1 单元测试清单（`packages/fetch/src/net/*.test.ts`）

| # | 用例 | 断言 |
|---|---|---|
| T1 | `https://export.arxiv.org/api/query?...` | 放行；`fetch` mock 被调用 1 次 |
| T2 | `https://arxiv.org.evil.com/x`、`https://example.com/x` | 均 `FR-NET-001`；`fetch` **未被调用** |
| T3 | `http://api.crossref.org/works/…` | `FR-NET-002` |
| T4 | `http://127.0.0.1:11434/api/tags`（`allowLocal: false` / `true`） | 前者 `FR-NET-002 reason='http_forbidden'`；后者放行 |
| T5 | `http://192.168.1.10:11434/…`（`allowLocal: true`） | `FR-NET-006 reason='ssrf_private'`（私网例外仅限回环） |
| T6 | `https://sci-hub.se/10.1000/x`、`https://www.annas-archive.org/…` | 均 `FR-NET-003 reason='denylist'`，**重试计数 === 0**（永不重试） |
| T7 | 重定向 `api.crossref.org → evil.com` / 4 跳全白名单链 | 均 `FR-NET-003 reason='allowlist'`（跨域重新校验；超跳数） |
| T8 | DNS mock 返回 `127.0.0.1`（host 白名单）/ `169.254.1.1` | 均 `FR-NET-006 reason='ssrf_private'`，无 TCP 连接尝试 |
| T9 | 白名单含 `*.com`（构造非法配置） | 构建期校验失败（`pnpm verify` 红），**不引入错误码** |
| T10 | 响应头含 `Set-Cookie` | 请求头中无 `cookie` 被转发（§2.3.7） |
| T11 | 响应 > 200 MB（mock stream） | `FR-NET-003 reason='size_exceeded'` 且中断流 |
| T12 | 审计写盘失败（mock `fs` 抛错） | `FR-NET-006 reason='audit_unavailable'` 且**请求未发出** |
| T13 | 审计脱敏 | 输入 `?email=a@b.com` → 输出不含 `a@b.com`，含 `[REDACTED]` |
| T14 | 速率限制 | 3 次连续 arXiv 请求 → 第 2、3 次被排队（≥ 3 s 间隔），`details.reason='local_throttle'` |
| T15 | 用户点击例外（§2.3.9） | `user-click` + `confirmedByUser:false` → `FR-NET-003 reason='user_click_unconfirmed'`；`true` 放行且回 `whitelisted:false`；同一 URL 命中黑名单时仍 `reason='denylist'` |
| T16 | `FR-FETCH-001` 语义 | `is_oa === false` → `outcome='needs-user-session'` 且**不产生**任何后续下载请求（mock 调用数不增长） |
| T17 | 下载内容校验 | 响应体非 `%PDF-` 开头 → `FR-FETCH-006` 且**不落盘**（暂存文件被删除） |

### 8.2 CI 门禁

```yaml
# .github/workflows/ci.yml（合规相关步骤）
- run: pnpm forbid        # scripts/forbid-domains.sh：禁止域名/关键词 grep（§3.3）
- run: pnpm test --filter @freeread/fetch   # §8.1 全部用例，含黑名单/私网/http 拒绝
- run: pnpm test --filter @freeread/zotero  # §7 只读断言（hash/mtime 不变）
- run: pnpm license       # License Gate：黑名单许可 + THIRD_PARTY_NOTICES
```

任一失败 → 阻断合并（P0）。§8.1 的 T2/T6/T8/T12/T15/T16 为**合规关键用例**，禁止 `skip`/`only`（CI 用 grep 校验测试文件中这些用例名附近无 `.skip`/`.only`）。发布前人工复核：`plan §6.3` 的 `check-agpl-obligations.sh` + 本文件 §9 检查清单。

### 8.3 新增来源评审流程（`spec:` PR 模板）

1. **提出**：PR 必须包含 `docs/adr/ADR-xx-new-source-<id>.md`，逐条回答：
   a. 该来源的**许可与 ToS**（附 URL 与原文快照 `docs/license-snapshots/`）：是否允许程序化访问、是否明确禁止批量下载、是否有署名/邮箱要求；
   b. 是否属于 OA 或用户自有授权（**必须**二者之一，否则直接否决）；
   c. 速率限制与 `User-Agent` 规范（写入 §2.5 表）；d. 元数据字段映射与失败码（写入 §4 表）；
   e. 是否需要新增白名单条目（主机 + 允许子域 + 用途，且通过公共后缀检查）；
2. **评审**：至少 1 名维护者 + 1 名非作者评审；重点核对 §1 的 6 条禁止项与 §3.2 的行为模式；
3. **落库与测试**：更新本文件 §2.2/§2.5/§4 + `README.md §3`（若引入新术语）+ 变更记录；新增 Provider 必须有 `lookup`/`download` 单测 + 1 条"无 OA 时 `outcome='needs-user-session'` 且不再发起请求（`FR-FETCH-001`）"用例；
4. **否决示例**（写死在评审清单里）：任何"影子图书馆"、任何需要绕过访问控制的来源、任何要求伪造 UA 或规避速率限制的来源、任何禁止程序化访问（robots/ToS 明示）的来源。

## 9. 发布前合规检查清单（人工，逐项勾选）

| # | 检查项 | 证据 |
|---|---|---|
| 1 | `pnpm forbid` 通过，且新增"疑似"字符串均已在 PR 中说明 | CI 日志 |
| 2 | §8.1 全部合规关键用例通过 | CI 日志 |
| 3 | 代码中不存在白名单外的 `http://` 地址（grep `http://` 结果逐条核对） | PR 描述 |
| 4 | 白名单表与 §2.2 完全一致（含 `user-llm` 动态条目） | `packages/fetch/src/net/whitelist.ts` 快照 |
| 5 | Zotero 只读断言通过（hash/mtime 不变）；README 与首次启动提示含 §1 声明义务文本 | CI 日志 + 截图 |
| 6 | 审计日志可查看、可导出、脱敏用例通过、保留 30 天 | 手动验证记录 |
| 7 | `THIRD_PARTY_NOTICES.md` 与 `SOURCE_OFFER.md` 已更新（AGPL 义务） | 生成物 |

## 变更记录

| 版本 | 日期 | 变更 | 影响 |
|---|---|---|---|
| v1.0 | 2026-10-03 | 首版冻结：原则声明与 6 条禁止项（C1–C6）、`NetGuard` 接口与白名单/协议/DNS 校验规则、黑名单与 `scripts/forbid-domains.sh` 门禁、6 个 `FetchProvider` 协议、元数据归一化与相似度阈值 0.75、审计日志与脱敏、Zotero 只读约束、17 条合规单测与新增来源评审流程 | 新增模块 `packages/fetch/src/net/{net-guard,whitelist,blocklist,private-ranges}.ts`；**同 PR 必须完成**：① `11-error-handling.md` §3 登记 `FR-NET-006`（`reason ∈ {ssrf_private, ip_literal, audit_unavailable}`）与 `FR-FETCH-006/007/008`；② 本文件 `FR-NET-002/003` 的 `details.reason` 枚举（`scheme_forbidden`/`allowlist`/`denylist`/`user_click_unconfirmed`）已由 `06-ipc-contract.md` §5.3 N2–N6 引用，改动需同步；③ `06-ipc-contract.md` 的 `fr:fetch:fetchOpenAccess` 通道表需补 `FR-FETCH-001`（"无 OA"原本未列）；④ 审计文件在本文件与 `06` 中名为 `logs/net-audit.jsonl`（实现为 `net-audit-YYYY-MM-DD.jsonl` 轮转），命名以 `05-storage.md` 日志小节为最终依据 |
