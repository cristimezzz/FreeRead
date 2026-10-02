import { defineConfig } from 'electron-vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  main: { build: { externalizeDeps: { exclude: ['@freeread/core'] }, rollupOptions: { input: 'src/main/index.ts' } } },
  preload: { build: { externalizeDeps: { exclude: ['@freeread/core'] }, rollupOptions: { input: 'src/preload/index.ts' } } },
  renderer: { root: 'src/renderer', plugins: [react()], build: { minify: true } },
});
