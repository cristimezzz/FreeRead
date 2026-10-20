# M2-6：Zotero 数据库快照导入与增量同步

- 日期：2026-10-20
- 关联：[路线图 M2](../04-roadmap.md)、[架构 §5.1](../01-architecture.md)、[M0 Zotero 本地 API](../m0/zotero-local-api.md)、[数据模型 sync_state](../03-data-model.md)

## 结论速览

| 项目 | 结果 |
|---|---|
| 数据源 | 设置 › Zotero › 数据来源：自动（默认）/ 只用本地 API / 只用数据库快照；数据目录可改（默认 `~/Zotero`） |
| 自动 | 先连本地 API；连不上（Zotero 没运行或没开本地 API）且数据目录里有 `zotero.sqlite` 时改读快照 |
| 快照 | 把 `zotero.sqlite`（连同 `-journal` / `-wal`）复制到数据目录的 `zotero-snapshots/` 再读副本，**不写原库**；复制前后文件有变化时重试，仍变化就报错 |
| 增量 | 本地 API：`items?since=<上次版本>` 取变化的条目，`items?format=versions` 一次取回全部现存 key 发现删除 / 移入回收站 |
| 全量 | 第一次、库版本为 0、距上次全量超过 7 天、用户点"完全同步"、数据源取不到 key 列表、快照（本地读库很快，总是全量） |
| 本机实测 | 47 条 / 6 个分类：快照与本地 API 读到的条目、分类、PDF 数一致（库版本 1575）；第二次同步为增量，0 变化；原库文件哈希与修改时间不变 |

## 设计

### 快照连接器（`infra/zotero/sqlite_snapshot.py`）

- 只读用户库（`libraries.type = 'user'`），不读群组库；`deletedItems` / `deletedCollections` 里的（回收站）不读；笔记、标注不是文献。
- 字段从 `itemData` + `itemDataValues` + `fieldsCombined`（Zotero 7，自定义字段）读取，旧版本退回 `fields`；条目类型同理（`itemTypesCombined` / `itemTypes`）。
- 作者 `fieldMode = 1` 是单字段姓名（机构），写成 `{name}`，和本地 API 一致。
- 附件 `linkMode` 0–3 对应 `imported_file` / `imported_url` / `linked_file` / `linked_url`；`storage:<文件名>` 在 `storage/<附件 key>/` 下找，链接文件用绝对路径。`attachments:` 开头的相对路径（Zotero 的"链接附件根目录"）暂不支持，计入缺失文件。
- 没有父条目的 PDF 作为独立条目导入（`extra.standalone`），和本地 API 连接器一致。
- 只是复制再读，所以 Zotero 正在运行时也能读（本机实测可以），但 auto 模式下这时会先用本地 API。

### 增量同步（`services/library.py`）

本地 API 没有 Web API 的 `/deleted` 端点（返回 `No endpoint found`）。但 `items?format=versions` 一次返回全部现存条目（含附件、笔记，不含回收站）的 `{key: version}`，不分页（`Total-Results` 与返回数量一致；不一致时视为不支持，退回全量）。

1. `since` 只用于普通条目；附件每次全量读（只有元数据），所以变化了的条目带着完整的附件列表。只变了附件的条目按 `itemKey` 补读父条目。
2. 不在现存 key 里的条目归档，不在其中的附件从条目上移除。
3. 解析任务：范围内（全部，或"同步此分类"的分类及子分类）现有条目的 PDF 都检查一遍，待解析的建任务。增量时没变化的条目不在这次的结果里，但"同步此分类"仍要为它们排队解析。
4. 同步结果写 `sync_state`（按数据源分行）：`last_version`、`last_synced_at`，全量时还写 `last_full_sync_at`。任务结束信息以"全量（本地 API）""增量（本地 API）""全量（数据库快照）"开头。

为什么还要定期全量：Zotero 的版本号在同步到 zotero.org 时才增长，本地改了还没同步的条目 `since` 看不到；没用 Zotero 云同步的库版本一直是 0，只能全量。

### 接口与界面

- `POST /library/sync {collection_key?, full}`：`full=true` 强制全量。
- `GET /library/sync/state`：各数据源上次同步的版本与时间。
- 设置 `zotero: {source: "auto" | "local_api" | "sqlite", data_dir}`。
- 设置 › Zotero：数据来源、数据目录（桌面版可用目录选择框）、上次同步、"完全同步"按钮。
- `LocalApiConnector.source_id` 从 `zotero-local` 改为 `zotero_local`，与 `sync_state.source` 一致。

## 验证

- `core`：255 个测试通过，新增：
  - `tests/test_zotero_sqlite.py` 3 个：用最小化的 Zotero 7 表结构造库，验证分类层级、回收站 / 群组库 / 笔记排除、字段与作者（含单字段姓名）、标签、导入与链接附件、独立 PDF、库版本、原库不变；数据库不存在时的错误；auto 回退到快照及两边都不可用时的错误。
  - `tests/test_zotero_local_api.py` 2 个：增量时只变了附件的条目补读父条目、附件不带 `since`；`format=versions` 取 key、被截断时视为不支持。
  - `tests/test_library.py` 4 个：首次全量、无变化增量、增量里的修改 / 删除 / 附件移除、强制全量；取不到 key、超过 7 天、版本 0 时退回全量；增量下"同步此分类"仍为没变化的条目建解析任务；API。
- 本机（Zotero 7 正在运行）：
  - 快照连接器读本机库：6 个分类、47 条、47 个 PDF 全部找到，库版本 1575；原库哈希和修改时间不变。
  - 本地 API 读到的数量相同；`deleted?since=` 返回 404，`format=versions` 返回 128 个 key（含附件、笔记）。
  - 开发版 sidecar 上同步两次：第一次"全量（本地 API）：新增 47"，第二次"增量（本地 API）：新增 0，更新 0，归档 0"；设置页显示上次同步与上次全量时间。

## 遗留

- [ ] Zotero 没运行时的快照同步只在测试库上验证过，**需要用户**关闭 Zotero 后点一次同步确认。
- [ ] `attachments:` 相对路径（链接附件根目录）需要读 Zotero 的 `prefs.js`。
- [ ] 群组库、Zotero Web API 同步与写回（M4）。
- [ ] 本地未同步到 zotero.org 的修改要等 7 天全量或手动"完全同步"才会进来；可以改用 `dateModified` 比较（快照里有，本地 API 的 `format=versions` 没有）。
