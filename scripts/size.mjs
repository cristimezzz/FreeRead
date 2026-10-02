import { readdir, readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
const dir = 'apps/desktop/out/renderer/assets';
let bytes = 0;
for (const file of await readdir(dir)) bytes += gzipSync(await readFile(`${dir}/${file}`)).length;
console.log(`Renderer gzip: ${(bytes / 1024).toFixed(1)} KiB`);
if (bytes > 1.5 * 1024 * 1024) throw new Error('Renderer exceeds 1.5 MiB gzip budget');
