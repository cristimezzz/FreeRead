// 更新历史页在浏览器里再向 GitHub 取一次 Releases，发布或修改更新说明后不必等文档站重新构建。
// 用 GitHub 渲染好的 body_html，不在浏览器里带 Markdown 解析器；取不到时页面保留构建时的内容。

import {
  compareVersions,
  formatDate,
  releaseId,
  releasesApi,
  safeReleaseUrl,
  VERSION_RE,
  type GitHubRelease,
  type Release,
} from '../releases'

const CACHE_KEY = 'freeread-docs-releases'
const CACHE_MS = 10 * 60 * 1000

const DROP = 'script, style, iframe, object, embed, form, input, button, a.anchor'

/** 整理 GitHub 的正文 HTML：去掉标题外壳和锚点、标题降一级、外链新窗口打开。 */
function tidy(html: string): string {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html')
  const root = doc.body.firstElementChild as HTMLElement
  root.querySelectorAll(DROP).forEach((el) => el.remove())
  // <div class="markdown-heading"><h2>…</h2></div>、<markdown-accessiblity-table> 这类外壳只留内容
  root.querySelectorAll('.markdown-heading, markdown-accessiblity-table').forEach((el) => el.replaceWith(...el.childNodes))
  root.querySelectorAll('*').forEach((el) => {
    for (const a of [...el.attributes]) {
      if (a.name.startsWith('on') || a.name === 'style' || a.name === 'dir') el.removeAttribute(a.name)
    }
  })
  // 每个版本在页面上占 h2，正文标题统一降一级
  root.querySelectorAll('h1, h2, h3, h4, h5').forEach((h) => {
    const n = doc.createElement(`h${Number(h.tagName[1]) + 1}`)
    n.append(...h.childNodes)
    h.replaceWith(n)
  })
  root.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href') ?? ''
    if (!/^(https?:|mailto:|#)/i.test(href)) a.removeAttribute('href')
    else if (/^https?:/i.test(href)) {
      a.setAttribute('target', '_blank')
      a.setAttribute('rel', 'noreferrer')
    }
  })
  return root.innerHTML
}

function readCache(): Release[] | null {
  try {
    const c = JSON.parse(sessionStorage.getItem(CACHE_KEY) ?? 'null')
    if (c && Date.now() - c.at < CACHE_MS && Array.isArray(c.releases)) return c.releases
  } catch {}
  return null
}

export async function loadLiveReleases(): Promise<Release[] | null> {
  const cached = readCache()
  if (cached) return cached
  try {
    const res = await fetch(releasesApi, {
      headers: { Accept: 'application/vnd.github.html+json' },
      signal: AbortSignal.timeout(8000),
    })
    if (!res.ok) return null
    const list = (await res.json()) as GitHubRelease[]
    if (!Array.isArray(list)) return null
    const releases = list
      .flatMap((r): Release[] => {
        const version = VERSION_RE.exec(r.tag_name ?? '')?.[1]
        if (r.draft || !version) return []
        return [{
          version,
          id: releaseId(version),
          date: formatDate(r.published_at),
          url: safeReleaseUrl(r.html_url, version),
          prerelease: !!r.prerelease,
          html: tidy(r.body_html ?? ''),
        }]
      })
      .sort((a, b) => compareVersions(b.version, a.version))
    if (!releases.length) return null
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), releases }))
    } catch {}
    return releases
  } catch {
    return null
  }
}
