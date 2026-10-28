// 最新 Release：页面构建时写入 apps/desktop/package.json 的版本作为兜底，
// 打开页面后向 GitHub 查询最新 Release 并替换。与主页 site/app.js 用同样的接口和缓存方式。

import { ref } from 'vue'

declare const __FREEREAD_VERSION__: string

export const REPO = 'https://github.com/cristimezzz/FreeRead'
const API = 'https://api.github.com/repos/cristimezzz/FreeRead/releases/latest'
const KEY = 'freeread-docs-release'
// GitHub API 匿名限流每 IP 每小时 60 次，缓存一小时
const TTL = 60 * 60 * 1000

export interface Asset {
  name: string
  url: string
}
export interface Release {
  version: string
  assets: Asset[]
}

// 安装包文件名规则，与 apps/desktop/src-tauri/src/update.rs 一致
export const PACKAGES = [
  { key: 'setup', label: 'Windows 安装包', suffix: '_x64-setup.exe', name: (v: string) => `FreeRead_${v}_x64-setup.exe` },
  { key: 'portable', label: 'Windows 便携版', suffix: '_x64-portable.zip', name: (v: string) => `FreeRead_${v}_x64-portable.zip` },
  { key: 'appimage', label: 'Linux AppImage', suffix: '_amd64.AppImage', name: (v: string) => `FreeRead_${v}_amd64.AppImage` },
  { key: 'deb', label: 'Debian / Ubuntu', suffix: '_amd64.deb', name: (v: string) => `FreeRead_${v}_amd64.deb` },
  { key: 'rpm', label: 'Fedora / openSUSE', suffix: '.x86_64.rpm', name: (v: string) => `FreeRead-${v}-1.x86_64.rpm` },
]

function fallback(version: string): Release {
  return {
    version,
    assets: PACKAGES.map((p) => {
      const name = p.name(version)
      return { name, url: `${REPO}/releases/download/v${version}/${name}` }
    }),
  }
}

export const release = ref<Release>(fallback(__FREEREAD_VERSION__))
let started = false

async function fetchLatest(): Promise<Release> {
  try {
    const c = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    if (c && Date.now() - c.at < TTL) return c.release
  } catch {}
  const r = await fetch(API, { headers: { Accept: 'application/vnd.github+json' } })
  if (!r.ok) throw new Error(`GitHub ${r.status}`)
  const j = await r.json()
  const latest: Release = {
    version: String(j.tag_name).replace(/^v/, ''),
    assets: j.assets.map((a: any) => ({ name: a.name, url: a.browser_download_url })),
  }
  try {
    localStorage.setItem(KEY, JSON.stringify({ at: Date.now(), release: latest }))
  } catch {}
  return latest
}

// 在组件 onMounted 里调用（只在浏览器里运行）；多个组件共用一次请求
export function loadLatest() {
  if (started) return
  started = true
  fetchLatest().then(
    (r) => {
      if (r.version) release.value = r
    },
    () => {},
  )
}
