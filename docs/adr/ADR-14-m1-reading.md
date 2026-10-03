# ADR-14 · M1 阅读内核的持久化与最小锚点

- 日期：2026-10-03；状态：接受；范围：M1。
- 冲突：02 §5 / T-003 要求 meta.json 保存 ReadingProgress，meta schema v1 不允许 reading；05 PR5 却允许进度丢失。以产品位置恢复承诺为准。
- 决策：meta schemaVersion 升为 2，新增可选 reading（完整位置、模式、UTC 毫秒、幂等事件 ID）。v1 经纯迁移升为 v2；原文件仅在校验通过、原子写成功后替换。SQLite 仅镜像进度。元数据读取错误不重置用户文件。
- 写入：每次聚焦句子即发 IPC，主进程同步 fsync + rename 后应答；滚动停止、隐藏、离开再保存。失败同步追加 .oplog.jsonl 的 progress.save，启动按文件顺序补偿；两处均失败返回 AppError，界面明确报错。
- SQLite：使用 Electron 39 / Node 22.13+ 内置 node:sqlite，代替 better-sqlite3；DDL 与真源顺序不变。无新原生模块、无 Electron ABI 重建。
- M1 最小锚点：PDF.js 文本项按视觉 y/x 排序，每项一个低置信 text 块，Intl.Segmenter 切句并保存原始 LineRef。仅支撑原文定位、标注与全文检索；不宣称完成 M2 的 XY-Cut、版面指标、OCR 或重排。
- 导入：逐个文件在 worker 提取文本与页数，可取消并报告不确定进度；renderer 文件选择通过 preload 的单一系统对话框方法，路径授权只留主进程，不允许 renderer 构造任意读取路径。PDF 本地协议按 docId 查库、realpath 包含性校验并支持 Range。
- M1 界面沿用 07 的阅读布局、颜色与原文模式；重排/翻译/Agent 随各自里程碑实现，不提供失效按钮。hash 路由以浏览器原生 API 实现，无需新增路由依赖。
- 验收：E2/E4/E6/E11/E14/E15；M1 强杀主进程恢复 20/20、1000 页首屏和 10 秒滚动指标保留原阈值。固定硬件未配置时记录实际环境与缺口，禁止声称正式性能验收完成。

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-03 | 解决进度真源冲突，确定 M1 实现范围 |
