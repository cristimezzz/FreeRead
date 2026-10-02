import { readFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { isAllowed } from './license-policy.mjs';

const entries = JSON.parse(await readFile('fixtures/golden/index.json', 'utf8'));
if (entries.length < 10) throw new Error('M0 requires at least 10 redistributable papers');
const ids = new Set();
for (const entry of entries) {
  if (ids.has(entry.id)) throw new Error(`Duplicate fixture: ${entry.id}`);
  ids.add(entry.id);
  if (!/^[a-z0-9-]+$/.test(entry.id) || entry.file !== `${entry.id}/paper.pdf`) throw new Error('Invalid fixture path');
  if (!isAllowed(entry.license) || !entry.source.startsWith('https://') || !entry.title || !entry.authors?.length || !entry.licenseEvidence || !Number.isInteger(entry.pages) || entry.pages < 1) throw new Error(`Incomplete provenance: ${entry.id}`);
  const pdf = await readFile(`fixtures/golden/${entry.file}`);
  if (pdf.subarray(0, 5).toString() !== '%PDF-' || !pdf.subarray(-1024).toString().includes('%%EOF')) throw new Error(`Invalid PDF: ${entry.id}`);
  if (createHash('sha256').update(pdf).digest('hex') !== entry.sha256) throw new Error(`Fixture hash drift: ${entry.id}`);
}
const directories = (await readdir('fixtures/golden', { withFileTypes: true })).filter((entry) => entry.isDirectory() && entry.name !== 'synthetic');
if (directories.length !== entries.length) throw new Error('Unindexed fixture directory');
console.log(`Fixtures: ${entries.length} licensed PDFs, hashes verified`);
