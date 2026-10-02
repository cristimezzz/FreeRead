import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { setTimeout, clearTimeout } from 'node:timers';
import { BUDGETS } from '../packages/core/dist/budgets.js';

const require = createRequire(import.meta.url);
const userData = await mkdtemp(resolve(tmpdir(), 'freeread-cold-'));
const env = { ...process.env, ELECTRON_RENDERER_URL: '' };
delete env['ELECTRON_RUN_AS_NODE'];
const start = Date.now();
const child = spawn(require('electron'), [resolve('apps/desktop'), `--user-data-dir=${userData}`, '--fr-benchmark'], { env });
let output = '';
let elapsed;
let mainElapsed;
child.stdout.on('data', (chunk) => {
  output += chunk.toString();
  if (mainElapsed === undefined && output.includes('"event":"app.main"')) mainElapsed = Date.now() - start;
  if (elapsed === undefined && output.includes('"event":"app.ready"')) elapsed = Date.now() - start;
});
child.stderr.on('data', (chunk) => process.stderr.write(chunk));
const timeout = setTimeout(() => child.kill(), 15_000);
try {
  const code = await new Promise((accept, reject) => {
    child.once('error', reject);
    child.once('exit', accept);
  });
  if (code !== 0 || elapsed === undefined) throw new Error(`Cold launch failed: code=${code}`);
  console.log(`Cold launch: ${elapsed} ms (budget ${BUDGETS.COLD_START_MS} ms, no debugger)`);
  console.log(`Native bootstrap: ${mainElapsed} ms; main-to-first-frame: ${elapsed - mainElapsed} ms`);
  if (elapsed > BUDGETS.COLD_START_MS) throw new Error('Cold launch exceeds BUDGETS.COLD_START_MS');
} finally {
  clearTimeout(timeout);
  await rm(userData, { recursive: true, force: true });
}
