import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
await mkdir('artifacts', { recursive: true });
const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const manifest = {
  git_sha: sha, dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim()),
  lock_sha256: createHash('sha256').update(await readFile('pnpm-lock.yaml')).digest('hex'),
  node: process.version, platform: process.platform, arch: process.arch,
  source_date_epoch: process.env['SOURCE_DATE_EPOCH'] ?? execFileSync('git', ['show', '-s', '--format=%ct', 'HEAD'], { encoding: 'utf8' }).trim(),
  build_id: process.env['BUILD_ID'] ?? 'local', python: null,
};
await writeFile('artifacts/build-manifest.json', JSON.stringify(manifest, null, 2) + '\n');
