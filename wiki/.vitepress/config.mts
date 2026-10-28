import { readFileSync } from 'node:fs'
import { defineConfig } from 'vitepress'

// 使用说明站点：docs.freeread.work，由 Cloudflare Pages 从 wiki/ 构建（输出 .vitepress/dist）。
// 设计文档（docs/）不上站，开发者指南里直接链接到 GitHub。

const repo = 'https://github.com/cristimezzz/FreeRead'

// 构建时的应用版本，页面打开后由 theme/release.ts 换成 GitHub 上的最新 Release
const appVersion: string = JSON.parse(
  readFileSync(new URL('../../apps/desktop/package.json', import.meta.url), 'utf8'),
).version

// 中文没有空格分词，按 Intl.Segmenter 切词后再交给 MiniSearch。
// 这个函数会被序列化后送到浏览器执行，不能引用外部变量。
const tokenize = (text: string) =>
  Array.from(new Intl.Segmenter('zh-CN', { granularity: 'word' }).segment(text))
    .filter((s) => s.isWordLike)
    .map((s) => s.segment)

export default defineConfig({
  lang: 'zh-CN',
  title: 'FreeRead 文档',
  description: 'FreeRead 使用说明：安装、导入文献、阅读、翻译、AI 总结、问答与知识图谱。',
  cleanUrls: true,
  vite: { define: { __FREEREAD_VERSION__: JSON.stringify(appVersion) } },
  sitemap: { hostname: 'https://docs.freeread.work' },
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
    ['link', { rel: 'preload', href: '/fonts/ibm-plex-sans-latin-400-normal.woff2', as: 'font', type: 'font/woff2', crossorigin: '' }],
    ['link', { rel: 'preload', href: '/fonts/source-serif-4-latin-opsz-normal.woff2', as: 'font', type: 'font/woff2', crossorigin: '' }],
  ],

  themeConfig: {
    logo: '/favicon.svg',
    siteTitle: 'FreeRead 文档',

    nav: [
      { text: '主页', link: 'https://freeread.work' },
      { text: '下载', link: `${repo}/releases/latest` },
      { text: '问题反馈', link: `${repo}/issues` },
    ],
    socialLinks: [{ icon: 'github', link: repo }],

    sidebar: [
      { text: '开始', items: [
        { text: '首页', link: '/' },
        { text: '安装', link: '/install' },
        { text: '快速上手', link: '/quick-start' },
      ] },
      { text: '使用', items: [
        { text: '导入文献', link: '/import' },
        { text: '阅读器', link: '/reader' },
        { text: '翻译与术语表', link: '/translation' },
        { text: 'AI 总结', link: '/summary' },
        { text: '文献问答', link: '/qa' },
        { text: '知识图谱', link: '/knowledge-graph' },
        { text: '批注与导出', link: '/annotations' },
      ] },
      { text: '设置', items: [
        { text: '大模型服务', link: '/llm-services' },
        { text: '解析引擎', link: '/parsers' },
        { text: '检索与语义索引', link: '/search' },
        { text: '隐私与数据', link: '/privacy' },
      ] },
      { text: '其他', items: [
        { text: '常见问题', link: '/faq' },
        { text: '开发者指南', link: '/developer' },
      ] },
    ],

    search: {
      provider: 'local',
      options: {
        miniSearch: {
          options: { tokenize },
          searchOptions: { tokenize, prefix: true, fuzzy: 0.2 },
        },
        translations: {
          button: { buttonText: '搜索', buttonAriaLabel: '搜索' },
          modal: {
            displayDetails: '显示详细列表',
            resetButtonTitle: '清除',
            backButtonTitle: '关闭搜索',
            noResultsText: '没有找到',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },

    editLink: { pattern: `${repo}/edit/main/wiki/:path`, text: '在 GitHub 上编辑此页' },

    outline: { level: [2, 3], label: '本页目录' },
    docFooter: { prev: '上一页', next: '下一页' },
    darkModeSwitchLabel: '深浅色',
    lightModeSwitchTitle: '切换到浅色',
    darkModeSwitchTitle: '切换到深色',
    sidebarMenuLabel: '目录',
    returnToTopLabel: '回到顶部',
    langMenuLabel: '语言',
    externalLinkIcon: true,
    notFound: { title: '页面不存在', quote: '这一页可能已经改名或移走了。', linkText: '回到首页' },
  },
})
