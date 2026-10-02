import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: {
    include: ['packages/**/*.test.ts', 'apps/**/*.test.ts'],
    coverage: {
      provider: 'v8', reporter: ['text', 'json-summary', 'html'],
      include: ['packages/*/src/**/*.ts'],
      exclude: ['**/*.generated.ts', '**/index.ts', '**/*.test.ts'],
      thresholds: { perFile: true, branches: 90, functions: 90, lines: 90, statements: 90 },
    },
  },
});
