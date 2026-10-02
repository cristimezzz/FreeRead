import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFile, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
const require = createRequire(import.meta.url);
const run = (file, args) => spawnSync(process.execPath, [file, ...args], { encoding: 'utf8' });

test('renderer fs import fails ESLint, and cycles fail dependency-cruiser', async () => {
  const renderer = 'apps/desktop/src/renderer/m0-gate-probe.ts';
  const first = 'packages/core/src/m0-cycle-a.ts';
  const second = 'packages/core/src/m0-cycle-b.ts';
  try {
    await writeFile(renderer, "import fs from 'fs';\nexport const probe = fs;\n");
    const lint = run(join(dirname(require.resolve('eslint/package.json')), 'bin/eslint.js'), [renderer]);
    assert.notEqual(lint.status, 0);
    assert.match(lint.stdout, /no-restricted-imports/);
    await writeFile(first, "import './m0-cycle-b';\nexport {};\n");
    await writeFile(second, "import './m0-cycle-a';\nexport {};\n");
    const cruise = run('node_modules/dependency-cruiser/bin/dependency-cruiser.mjs', [first, '--config', '.dependency-cruiser.cjs']);
    assert.notEqual(cruise.status, 0);
    assert.match(cruise.stdout, /no-circular/);
  } finally {
    await Promise.all([renderer, first, second].map((file) => rm(file, { force: true })));
  }
});
