import { test, expect } from 'vitest';
import { chromium, expect as expectPage } from '@playwright/test';
import { createServer } from 'node:http';
import { readFileSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve, extname } from 'node:path';
import { tmpdir } from 'node:os';
import { Worker } from 'node:worker_threads';
import { once } from 'node:events';
import type { DocAnchorModel, IpcPayloads } from '@freeread/core';
import { IndexStore } from '../infra/index-store';
import { LibraryService } from './library-service';
import { NoteService } from './note-service';
import { ReaderService } from './reader-service';
import { writePdf } from '../../../e2e/pdf-fixture';

// Supplemental browser QA when this host cannot launch Electron. Native E2E remains the gate.
test.runIf(process.env['FR_UI_PREVIEW'] === '1')('M1 real services + system browser supplemental UI check', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'fr-preview-')), source = join(dir, 'paper.pdf'); writePdf(source, 1000);
  const worker = new Worker(resolve('apps/desktop/out/main/pdf-worker.js'), { workerData: source });
  const model = await new Promise<DocAnchorModel>((resolve, reject) => {
    worker.on('error', reject); worker.on('message', (value: { model?: DocAnchorModel; error?: unknown }) => {
      if (value.model) resolve(value.model); if (value.error) reject(value.error);
    });
  });
  const index = new IndexStore(join(dir, 'index.sqlite'));
  const library = new LibraryService(join(dir, 'library'), index, async () => model);
  const notes = new NoteService(library), reader = new ReaderService(library);
  const server = createServer((req, res) => {
    try {
      const path = req.url === '/paper.pdf' ? source : resolve('apps/desktop/out/renderer', '.' + (req.url === '/' ? '/index.html' : req.url));
      res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.pdf': 'application/pdf' })[extname(path)] ?? 'application/octet-stream');
      const bytes = readFileSync(path);
      res.end(extname(path) === '.html' ? bytes.toString().replace('connect-src fr-file:', "connect-src 'self'") : bytes);
    } catch { res.writeHead(404).end(); }
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No preview port');
  const base = `http://127.0.0.1:${address.port}`, browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on('pageerror', (error) => console.warn(error.message));
    await page.exposeFunction('frTestCall', async (domain: string, action: string, req: unknown) => {
      try { return { ok: true, data: await previewCall({ library, notes, reader, source, base }, domain, action, req) }; }
      catch (error) { return { ok: false, error }; }
    });
    await page.addInitScript(() => { const invoke = Reflect.get(window, 'frTestCall') as (domain: string, action: string, req: unknown) => Promise<unknown>;
      const domain = (name: string) => new Proxy({}, { get: (_target, action) => (req: unknown) => invoke(name, String(action), req) });
      Object.defineProperty(window, 'fr', { value: { library: domain('library'), doc: domain('doc'), notes: domain('notes'), app: domain('app'),
        local: { pickPdf: async () => { const r = await invoke('local', 'pickPdf', {}) as { data: string[] }; return r.data; } } } }); });
    await page.goto(base);
    await page.screenshot({ path: 'test-results/m1-library-browser.png' });
    await page.getByRole('button', { name: '导入 PDF' }).click();
    await page.waitForSelector('.fr-document-open');
    const start = Date.now(); await page.locator('.fr-document-open').click();
    await page.waitForSelector('[data-sentence-id="s_b_1_1_2"]');
    const firstPaint = Date.now() - start; expect(firstPaint).toBeLessThanOrEqual(3000);
    await page.locator('[data-sentence-id="s_b_1_1_2"]').focus();
    await page.waitForFunction(() => document.querySelector('.fr-status')?.getAttribute('data-saved') === 'true');
    await page.getByRole('button', { name: '高亮', exact: true }).click();
    await expectPage(page.locator('.fr-highlight-yellow')).toHaveCount(1);
    await expectPage(page.getByRole('alert')).toHaveCount(0);
    await page.getByLabel('当前句子的笔记').fill('A local insight.'); await page.getByRole('button', { name: '保存笔记' }).click();
    await page.getByText('A local insight.').waitFor();
    await page.screenshot({ path: 'test-results/m1-reader-browser.png' });
    const rectangle = await page.locator('[data-sentence-id="s_b_1_1_2"]').boundingBox(); expect(rectangle?.height).toBeGreaterThan(8);
    const fps = await measureScroll(page); console.log(JSON.stringify({ firstPaintMs: firstPaint, fps, source: 'supplemental Edge browser, real worker and services' }));
    writeFileSync('test-results/m1-browser-performance.json', JSON.stringify({ firstPaintMs: firstPaint, fps, pages: 1000, browser: await browser.version(), source: 'supplemental browser QA' }));
    expect(fps).toBeGreaterThanOrEqual(55);
    expect(await page.locator('canvas').count()).toBeLessThanOrEqual(5);
  } finally { await browser.close(); server.close(); index.db.close(); await worker.terminate(); rmSync(dir, { recursive: true, force: true }); }
}, 60_000);

type Context = { library: LibraryService; notes: NoteService; reader: ReaderService; source: string; base: string };
async function previewCall(c: Context, domain: string, action: string, input: unknown): Promise<unknown> {
  switch (`${domain}.${action}`) {
    case 'app.doctor': return { checks: [] };
    case 'local.pickPdf': return [c.source];
    case 'library.import': return c.library.import(input as IpcPayloads['LibraryImportRequest'], new AbortController().signal, () => undefined);
    case 'library.list': return c.library.list(input as IpcPayloads['LibraryListRequest']);
    case 'library.listTags': return { tags: [] };
    case 'doc.open': return { ...c.reader.open(input as IpcPayloads['DocOpenRequest']), pdfUrl: `${c.base}/paper.pdf` };
    case 'doc.getAnchorModel': return c.reader.model(input as IpcPayloads['DocGetAnchorModelRequest']);
    case 'notes.list': return c.notes.list(input as IpcPayloads['NotesListRequest']);
    case 'notes.upsert': { const req = input as IpcPayloads['NotesUpsertRequest']; return c.notes.upsert(req.docId, req.annotation); }
    case 'notes.updateProgress': return c.notes.saveProgress(input as IpcPayloads['NotesUpdateProgressRequest']);
    case 'notes.exportMarkdown': { const req = input as IpcPayloads['NotesExportMarkdownRequest']; return { markdown: await c.notes.markdown(req.docId, false) }; }
    default: throw new Error(`Unhandled preview call ${domain}.${action}`);
  }
}
async function measureScroll(page: import('@playwright/test').Page) {
  return page.evaluate(() => new Promise<number>((resolve) => { const root = document.querySelector('.fr-reader-area');
    const start = performance.now(); let frames = 0;
    const frame = () => { frames++; if (root) root.scrollTop += 4;
      if (performance.now() - start < 10_000) requestAnimationFrame(frame); else resolve(frames * 1000 / (performance.now() - start)); };
    requestAnimationFrame(frame); }));
}
