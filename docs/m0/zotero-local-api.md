# M0：Zotero 7 本地 API 验证

- 日期：2026-10-17
- 实现：[`core/freeread/infra/zotero/local_api.py`](../../core/freeread/infra/zotero/local_api.py)（`LocalApiConnector`）
- 复现：先启动 Zotero 7，再运行 `core/.venv/Scripts/python scripts/m0_zotero_check.py --json docs/m0/zotero-check.json`

## 结论

**可行，作为默认接入方式。** 在本机 Zotero 7 库上，本地 API 能拿到全部分类、条目及其 PDF 附件的本地路径，耗时约 1.4 秒。

| 项 | 结果 |
|---|---|
| 分类 | 6 / 6（含中文名称） |
| 顶层条目（排除附件、笔记、批注） | 47 |
| 有分类的条目 | 44 |
| 有父条目的 PDF 附件 | 67 |
| 解析出本地路径的 PDF | **67 / 67**，全部来自 `links.enclosure.href`（`file:///` URL） |
| 全量拉取耗时 | 1.42 s |

原始数据：[zotero-check.json](zotero-check.json)。

## 要点

- 前提：Zotero 7 正在运行，并启用了"允许此计算机上的其他应用程序与 Zotero 通信"（`extensions.zotero.httpServer.localAPI.enabled`）。本机已启用。
- 接口与 Web API v3 相同，库前缀为 `/api/users/0/`。分页靠 `limit`/`start` 和响应头 `Total-Results`，每页最多 100 条。
- 条目列表与附件分两次请求（`itemType=-attachment` 和 `itemType=attachment`），再按 `parentItem` 归组，避免每个条目都请求一次 `/children`。
- 附件路径：优先取本地 API 给出的 `links.enclosure.href`（`file:///…`），其次是链接文件的 `data.path`，最后回退到 `<dataDir>/storage/<key>/<filename>`。
- 只读查询 `zotero.sqlite` 可以看到 75 个未删除的 PDF 附件，比本地 API 条目下挂的 67 个多 8 个。差额主要是没有父条目的独立附件（例如翻译插件生成的副本），它们不会出现在条目的附件中。M1 需要决定是否把它们作为独立文献导入。
- Zotero 未运行时，连接器抛出 `ZoteroUnavailableError` 并给出明确提示。M2 的 `SqliteSnapshotConnector` 用于这种场景。
- 只读：连接器只发 GET 请求。

## 对 M1 的影响

- `ZoteroConnector.Attachment` 增加了 `link_mode`、`path`、`href` 三个字段（`infra/zotero/base.py`）。
- 增量同步可以直接用 `since=<version>` 参数，连接器已支持。
