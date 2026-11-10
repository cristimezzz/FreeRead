// 更新历史页的共用部分：构建期加载器（changelog.data.ts）和浏览器端刷新（theme/liveReleases.ts）都用。

export const owner = 'cristimezzz'
export const name = 'FreeRead'
export const releasesApi = `https://api.github.com/repos/${owner}/${name}/releases?per_page=100`
export const releasesPage = `https://github.com/${owner}/${name}/releases/`
export const tagUrl = (version: string) => `${releasesPage}tag/v${version}`

export interface Release {
  version: string
  /** 锚点，如 v0-2-1 */
  id: string
  /** YYYY-MM-DD；回退到本地文件时没有日期 */
  date: string | null
  url: string
  prerelease: boolean
  /** 已渲染的正文 HTML */
  html: string
}

/** GitHub API 返回的字段（只列用到的） */
export interface GitHubRelease {
  tag_name: string
  published_at: string | null
  html_url: string
  body?: string | null
  body_html?: string | null
  draft: boolean
  prerelease: boolean
}

export const VERSION_RE = /^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$/

export const releaseId = (version: string) => 'v' + version.replace(/\./g, '-')

const dateFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

export function formatDate(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : dateFormat.format(d)
}

/** 只接受本仓库 Releases 下的链接 */
export const safeReleaseUrl = (url: unknown, version: string) =>
  typeof url === 'string' && url.startsWith(releasesPage) ? url : tagUrl(version)

/** 语义化版本比较（降序用 b, a）；预发布排在同号正式版之前。 */
export function compareVersions(a: string, b: string): number {
  const [coreA, preA] = a.split('-', 2)
  const [coreB, preB] = b.split('-', 2)
  const pa = coreA.split('.').map(Number)
  const pb = coreB.split('.').map(Number)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (d) return d
  }
  if (preA === preB) return 0
  if (!preA) return 1
  if (!preB) return -1
  return preA.localeCompare(preB, 'en', { numeric: true })
}
