import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import boundaries from 'eslint-plugin-boundaries';
import importPlugin from 'eslint-plugin-import';

const privileged = ['fs', 'fs/promises', 'net', 'http', 'https', 'tls', 'dns', 'dgram',
  'child_process', 'worker_threads', 'electron', 'axios', 'got', 'undici'];
const policy = (from, types) => ({ from: { element: { type: from } },
  allow: { to: { element: { types: { anyOf: types } } } } });
export default tseslint.config(
  { ignores: ['**/dist/**', '**/out/**', '**/*.generated.ts', '**/node_modules/**', 'artifacts/**', 'coverage/**'] },
  js.configs.recommended, ...tseslint.configs.recommended,
  {
    languageOptions: { globals: { console: 'readonly', process: 'readonly', Buffer: 'readonly',
      __dirname: 'readonly', URL: 'readonly', document: 'readonly' } },
    rules: { complexity: ['error', 12], 'max-lines': ['error', { max: 400, skipBlankLines: true, skipComments: true }],
      'max-lines-per-function': ['error', { max: 60, skipBlankLines: true, skipComments: true }],
      '@typescript-eslint/no-explicit-any': 'error', 'no-empty': 'error',
      '@typescript-eslint/ban-ts-comment': ['error', { 'ts-ignore': true, 'ts-expect-error': 'allow-with-description' }] },
  },
  {
    files: ['apps/**/*.{ts,tsx}', 'packages/**/*.{ts,tsx}'],
    plugins: { boundaries, import: importPlugin },
    settings: {
      'boundaries/root-path': process.cwd(),
      'boundaries/elements': [
        { type: 'renderer', pattern: 'apps/desktop/src/renderer' },
        { type: 'preload', pattern: 'apps/desktop/src/preload' },
        { type: 'main', pattern: 'apps/desktop/src/main' },
        { type: 'cli', pattern: 'apps/cli' },
        ...['core', 'render-reflow', 'parser-protocol', 'translate', 'fetch', 'zotero', 'ui', 'agent']
          .map((type) => ({ type, pattern: `packages/${type}` })),
      ],
    },
    rules: {
      'boundaries/dependencies': ['error', { default: 'disallow', policies: [
        policy('renderer', ['renderer', 'ui', 'core']),
        policy('preload', ['preload', 'renderer', 'core']),
        policy('main', ['main', 'core', 'render-reflow', 'parser-protocol', 'translate', 'fetch', 'zotero', 'ui', 'agent']),
        policy('cli', ['cli', 'core', 'parser-protocol', 'fetch']),
        policy('core', ['core']),
        ...['render-reflow', 'parser-protocol', 'translate', 'fetch', 'zotero', 'ui', 'agent']
          .map((from) => policy(from, [from, 'core'])),
      ] }],
      'import/no-relative-packages': 'error',
    },
  },
  {
    files: ['apps/desktop/src/renderer/**/*.{ts,tsx}', 'packages/ui/src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', { paths: privileged, patterns: ['node:*', 'electron/*', '@freeread/core/*',
        '@freeread/fetch', '@freeread/translate', '@freeread/agent', '@freeread/parser-protocol', '@freeread/zotero', '@freeread/render-reflow'] }],
      'no-restricted-globals': ['error', 'fetch', 'XMLHttpRequest', 'WebSocket', 'require'],
      'no-restricted-properties': ['error', ...['window', 'globalThis'].flatMap((object) =>
        ['fetch', 'XMLHttpRequest', 'WebSocket', 'require'].map((property) => ({ object, property })))],
      'no-restricted-syntax': ['error', {
        selector: 'ImportDeclaration[source.value="@freeread/core"][importKind!="type"]',
        message: 'Renderer may only import core types.',
      }, { selector: 'ImportExpression', message: 'Renderer dynamic imports need an explicit boundary review.' }],
    },
  },
  {
    files: ['packages/core/src/**/*.ts'],
    rules: { 'no-restricted-imports': ['error', { patterns: ['node:*', 'electron', 'react', 'react-dom', '@freeread/*'] }] },
  },
);
