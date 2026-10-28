<script setup lang="ts">
// 行内显示最新版本号，链接到对应的 Release 页面
import { onMounted } from 'vue'
import { REPO, loadLatest, release } from './release'

onMounted(loadLatest)
</script>

<template>
  <a :href="`${REPO}/releases/tag/v${release.version}`"><strong>{{ release.version }}</strong></a>
</template>
