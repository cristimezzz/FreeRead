import { defineConfig } from 'electron-vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  main: { build: { externalizeDeps: { exclude: ['@freeread/core', 'ajv', 'ajv-formats', 'zod'] }, rollupOptions: {
    input: { index: 'src/main/index.ts', 'pdf-worker': 'src/main/services/pdf-worker.ts' } } } },
  preload: { build: { externalizeDeps: false, rollupOptions: { input: 'src/preload/index.ts' } } },
  renderer: { root: 'src/renderer', plugins: [react()], build: { minify: true } },
});
