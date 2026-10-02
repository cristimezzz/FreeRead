# ADR-02 前端框架：React ✅（可低成本换 Vue）

- 状态：接受；日期：2026-10-03
- 来源：[技术方案 §2](../../plan/FreeRead-技术方案与里程碑.md)

- **选择**：React 19 + Vite + Zustand（轻量状态） + TanStack Query（数据获取） + Tailwind CSS。
- **理由**：PDF 标注/虚拟列表/拖拽类库最丰富；Zustand 比 Redux 更适合"文档级多实例状态"。
- **被否**：Vue 3（Scholaread 同款，若团队更熟悉可直接换，仅影响 UI 层，不影响 §3.3 接口）。
- **风险**：无。
