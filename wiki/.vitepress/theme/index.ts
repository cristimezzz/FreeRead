import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import LatestDownloads from './LatestDownloads.vue'
import LatestVersion from './LatestVersion.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('LatestVersion', LatestVersion)
    app.component('LatestDownloads', LatestDownloads)
  },
} satisfies Theme
