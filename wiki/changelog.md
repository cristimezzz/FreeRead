---
outline: 2
editLink: false
---

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { getScrollOffset } from 'vitepress'
import { data } from './changelog.data'
import { loadLiveReleases } from './.vitepress/theme/liveReleases'

// 先显示构建时的内容，再用 GitHub 上的最新 Releases 替换
const releases = ref(data)
onMounted(async () => {
  const live = await loadLiveReleases()
  if (!live) return
  const hash = decodeURIComponent(location.hash.slice(1))
  const missing = hash && !document.getElementById(hash)
  releases.value = live
  // 链接指向构建后才发布的版本时，替换完再滚过去
  if (missing) {
    await nextTick()
    const el = document.getElementById(hash)
    if (el) scrollTo({ top: el.getBoundingClientRect().top + scrollY - getScrollOffset() })
  }
})
</script>

# 更新历史

各版本的新增、修复与已知限制，新版本在前。安装包在 [GitHub Releases](https://github.com/cristimezzz/FreeRead/releases) 下载，升级方法见 [安装 › 更新](/install#更新)。

<template v-for="r in releases" :key="r.version">
  <h2 :id="r.id" tabindex="-1">
    {{ r.version }}
    <a class="header-anchor" :href="'#' + r.id" :aria-label="'指向 ' + r.version + ' 的永久链接'">&#8203;</a>
  </h2>
  <p class="release-meta">
    <span v-if="r.prerelease" class="release-pre">预发布</span>
    <span v-if="r.date">{{ r.date }}</span>
    <a :href="r.url" target="_blank" rel="noreferrer">在 GitHub 查看</a>
  </p>
  <div class="release-body" v-html="r.html"></div>
</template>
