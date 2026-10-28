<script setup lang="ts">
// 最新版本各安装包的直接下载链接；Release 里没有的包不显示
import { computed, onMounted } from 'vue'
import { PACKAGES, loadLatest, release } from './release'

onMounted(loadLatest)

const rows = computed(() =>
  PACKAGES.flatMap((p) => {
    const asset = release.value.assets.find((a) => a.name.endsWith(p.suffix))
    return asset ? [{ label: p.label, ...asset }] : []
  }),
)
</script>

<template>
  <ul>
    <li v-for="r in rows" :key="r.name">
      {{ r.label }}：<a :href="r.url"><code>{{ r.name }}</code></a>
    </li>
  </ul>
</template>
