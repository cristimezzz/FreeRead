import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
await mkdir('artifacts', { recursive: true });
const files = execFileSync('git', ['-c', 'core.quotepath=false', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], { encoding: 'utf8' }).split('\0').filter(Boolean).sort();
await writeFile('artifacts/source-files.txt', files.join('\n') + '\n');
execFileSync('tar', ['-czf', 'artifacts/source.tar.gz', '-T', 'artifacts/source-files.txt'], { stdio: 'inherit' });
console.log('Corresponding source: artifacts/source.tar.gz');
