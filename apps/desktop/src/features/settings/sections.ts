// 设置页的分节：侧栏锚点与页面里的 <section id> 一一对应。按重要性从上到下排列：
// 先是不配置就用不了的（大模型服务、翻译），再是影响阅读质量的（解析）与文献来源，最后是可选的个性化。

export const SETTINGS_SECTIONS = [
  { id: "providers", label: "大模型服务" },
  { id: "ai", label: "翻译、总结、问答与图谱" },
  { id: "parse", label: "解析" },
  { id: "zotero", label: "Zotero" },
  { id: "search", label: "检索" },
  { id: "glossary", label: "术语表" },
  { id: "appearance", label: "外观" },
  { id: "privacy", label: "隐私" },
  { id: "about", label: "关于" },
] as const;
