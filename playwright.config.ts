import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: 'apps/desktop/e2e', testMatch: '*.e2e.ts',
  retries: 0, workers: 1, timeout: 30_000,
  reporter: [['list'], ['html', { open: 'never' }]],
});
