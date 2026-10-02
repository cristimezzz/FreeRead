import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
await mkdir('artifacts', { recursive: true });
const files = execFileSync('git', ['-c', 'core.quotepath=false', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], { encoding: 'utf8' }).split('\0').filter(Boolean).sort();
execFileSync('tar', ['-czf', 'artifacts/source.tar.gz', ...files], { stdio: 'inherit' });
console.log('Corresponding source: artifacts/source.tar.gz');
