import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

const excluded = new Set(['node_modules', 'dist', 'out', '.git', '.turbo', 'coverage', 'artifacts', 'test-results', 'playwright-report']);
export async function sourceFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const nested = await Promise.all(entries.filter((entry) => !excluded.has(entry.name)).map(async (entry) => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? sourceFiles(file) : [file];
  }));
  return nested.flat();
}
export const forbiddenPattern = /sci[-_.]?hub|libgen\.|scihub\.|paywall[-_ ]?(bypass|circumvent)|institutional[-_ ]?proxy[-_ ]?bypass/i;
if (process.argv[1]?.endsWith('forbid-domains.mjs')) {
  const files = (await Promise.all(['apps', 'packages', 'services', 'plugins'].map(sourceFiles))).flat();
  const rejected = [];
  for (const file of files.filter((file) => /\.(ts|tsx|js|mjs|cjs|py|json|html|css|ya?ml|toml)$/.test(file))) {
    if (forbiddenPattern.test(await readFile(file, 'utf8'))) rejected.push(file);
  }
  if (rejected.length) throw new Error(`Forbidden content: ${rejected.join(', ')}`);
  console.log(`Forbidden-content gate: ${files.length} files checked`);
}
