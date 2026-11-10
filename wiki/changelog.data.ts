import fs from 'node:fs'
import path from 'node:path'
import { createMarkdownRenderer, defineLoader, type SiteConfig } from 'vitepress'
import {
  compareVersions,
  formatDate,
  releaseId,
  releasesApi,
  safeReleaseUrl,
  tagUrl,
  VERSION_RE,
  type GitHubRelease,
  type Release,
} from './.vitepress/releases'

// 更新历史：构建时从 GitHub Releases 拉取各版本说明；拉取失败（离线、限流）时
// 回退读仓库里的 docs/releases/<ver>.md——release workflow 就用它们作为 Release 正文，内容一致。

declare const data: Release[]
export { data }

interface RawRelease {
  version: string
  date: string | null
  url: string
  prerelease: boolean
  body: string
}

async function fromGitHub(): Promise<RawRelease[]> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'freeread-docs',
  }
  if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`

  const res = await fetch(releasesApi, { headers, signal: AbortSignal.timeout(10_000) })
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`)
  const list = (await res.json()) as GitHubRelease[]
  if (!Array.isArray(list) || list.length === 0) throw new Error('没有已发布的版本')

  return list.flatMap((r) => {
    const version = VERSION_RE.exec(r.tag_name)?.[1]
    if (r.draft || !version) return []
    return [{
      version,
      date: formatDate(r.published_at),
      url: safeReleaseUrl(r.html_url, version),
      prerelease: r.prerelease,
      body: r.body ?? '',
    }]
  })
}

function fromLocal(files: string[]): RawRelease[] {
  return files.map((file) => {
    const version = path.basename(file, '.md')
    return {
      version,
      date: null,
      url: tagUrl(version),
      prerelease: version.includes('-'),
      body: fs.readFileSync(file, 'utf-8'),
    }
  })
}

/** 每个版本在页面上占 h2，正文里的标题统一降一级；跳过代码块。 */
function demoteHeadings(src: string): string {
  let fence: string | null = null
  return src
    .split(/\r?\n/)
    .map((line) => {
      const m = line.match(/^\s{0,3}(`{3,}|~{3,})/)
      if (m) {
        if (!fence) fence = m[1]
        else if (m[1][0] === fence[0] && m[1].length >= fence.length) fence = null
        return line
      }
      if (fence) return line
      return line.replace(/^(\s{0,3})(#{1,5})(?=\s|$)/, '$1#$2')
    })
    .join('\n')
}

export default defineLoader({
  watch: ['../docs/releases/*.md'],
  async load(watchedFiles): Promise<Release[]> {
    let raw: RawRelease[]
    try {
      raw = await fromGitHub()
    } catch (err) {
      console.warn(`[changelog] 读取 GitHub Releases 失败（${(err as Error).message}），改用 docs/releases/*.md`)
      raw = fromLocal(watchedFiles)
    }
    raw.sort((a, b) => compareVersions(b.version, a.version))

    const config = (globalThis as any).VITEPRESS_CONFIG as SiteConfig
    const md = await createMarkdownRenderer(config.srcDir, config.markdown, config.site.base, config.logger)

    return raw.map((r) => ({
      version: r.version,
      id: releaseId(r.version),
      date: r.date,
      url: r.url,
      prerelease: r.prerelease,
      html: md.render(demoteHeadings(r.body), { relativePath: 'changelog.md', cleanUrls: config.cleanUrls }),
    }))
  },
})
