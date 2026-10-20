// 设置页的分节：侧栏锚点与页面里的 <section id> 一一对应。

export const SETTINGS_SECTIONS = [
  { id: "appearance", label: "外观" },
  { id: "ai", label: "翻译、总结、问答与图谱" },
  { id: "glossary", label: "术语表" },
  { id: "search", label: "检索" },
  { id: "providers", label: "大模型服务" },
  { id: "zotero", label: "Zotero" },
  { id: "parse", label: "解析" },
  { id: "privacy", label: "隐私" },
] as const;
