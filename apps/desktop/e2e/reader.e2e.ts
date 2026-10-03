import { test, expect } from '@playwright/test';
import type { ElectronApplication, Page } from '@playwright/test';
import { join } from 'node:path';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir, cpus, totalmem, release } from 'node:os';
import { writePdf } from './pdf-fixture';
import { launchElectron } from './electron-app';

async function launch(userData: string) {
  const app = await launchElectron(userData);
  const page = await app.firstWindow();
  page.on('pageerror', (error) => console.error(error));
  page.on('console', (message) => { if (message.type() === 'error') console.error(message.text()); });
  return app;
}
async function importPdf(app: ElectronApplication, page: Page, path: string) {
  await app.evaluate(({ dialog }, file) => { dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] }); }, path);
  await page.getByRole('button', { name: '导入 PDF' }).click();
  await expect(page.locator('.fr-import-status')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator('.fr-document-open')).toHaveCount(1);
}
test('E2/E4/E6/E11/E14/E15: dedup, tags/FTS, five exact restores, notes and renderer recovery', async () => {
  test.setTimeout(120_000);
  const dir = mkdtempSync(join(tmpdir(), 'fr-reader-e2e-')), source = join(dir, 'paper.pdf'); writePdf(source);
  const app = await launch(join(dir, 'user'));
  const appProcess = app.process();
  try {
    const page = await app.firstWindow(); await importPdf(app, page, source); await importPdf(app, page, source);
    await expect(page.getByText('该文献已在库中，已跳过重复导入')).toBeVisible();
    await page.getByLabel('搜索文献').fill('Attention'); await expect(page.locator('.fr-document-open')).toHaveCount(1);
    await page.getByLabel('搜索文献').fill(''); await page.locator('.fr-tag-edit input').fill('NLP'); await page.locator('.fr-tag-edit input').blur();
    for (let i = 0; i < 5; i++) {
      await page.locator('.fr-document-open').click();
      const sentence = page.locator('[data-sentence-id="s_b_1_1_2"]'); await sentence.focus();
      await expect(page.locator('.fr-status')).toHaveAttribute('data-saved', 'true');
      await page.getByRole('button', { name: '返回文献库' }).click(); await page.locator('.fr-document-open').click();
      await expect(page.locator('.fr-status')).toHaveAttribute('data-focused-sentence', 's_b_1_1_2');
      await page.getByRole('button', { name: '返回文献库' }).click();
    }
    await page.locator('.fr-document-open').click();
    await page.getByRole('button', { name: '笔记', exact: true }).click();
    await page.getByRole('button', { name: '高亮', exact: true }).click();
    await expect(page.locator('.fr-highlight-yellow')).toHaveCount(1);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await page.getByLabel('当前句子的笔记').fill('Offline insight'); await page.getByRole('button', { name: '保存笔记' }).click();
    await expect(page.getByText('Offline insight')).toBeVisible();
    await page.screenshot({ path: 'test-results/m1-reader.png' });
    await page.getByRole('button', { name: '返回文献库' }).click(); await app.close();
    const reopened = await launch(join(dir, 'user'));
    try { const p = await reopened.firstWindow(); await p.locator('.fr-document-open').click();
      await p.getByRole('button', { name: '笔记', exact: true }).click(); await expect(p.getByText('Offline insight')).toBeVisible();
      await expect(p.locator('.fr-highlight-yellow')).toHaveCount(1);
      await reopened.evaluate(({ BrowserWindow }) => new Promise<void>((resolve) => {
        const contents = BrowserWindow.getAllWindows()[0]?.webContents;
        if (!contents) throw new Error('Missing reader window');
        contents.once('did-finish-load', () => resolve()); contents.forcefullyCrashRenderer();
      }));
      await expect.poll(() => reopened.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.webContents
        .executeJavaScript("document.querySelector('.fr-status')?.getAttribute('data-focused-sentence')")))
        .toBe('s_b_1_1_2');
    } finally { await reopened.close(); }
  } finally { if (appProcess.exitCode === null) await app.close(); rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
});
test('M1 gate: force-kill main process and restore exact last sentence 20/20', async () => {
  test.setTimeout(180_000);
  const dir = mkdtempSync(join(tmpdir(), 'fr-kill-e2e-')), source = join(dir, 'paper.pdf'); writePdf(source);
  let app = await launch(join(dir, 'user'));
  try {
    await importPdf(app, await app.firstWindow(), source);
    for (let i = 0; i < 20; i++) {
      const page = await app.firstWindow(); await page.locator('.fr-document-open').click();
      const id = `s_b_1_1_${i % 2 + 1}`;
      await page.locator(`[data-sentence-id="${id}"]`).focus();
      await expect(page.locator('.fr-status')).toHaveAttribute('data-saved', 'true');
      const child = app.process(), exited = new Promise<void>((r) => child.once('exit', () => r()));
      if (process.platform === 'win32' && child.pid) execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F']);
      else child.kill('SIGKILL');
      await exited;
      app = await launch(join(dir, 'user'));
      const reopened = await app.firstWindow(); await reopened.locator('.fr-document-open').click();
      await expect(reopened.locator('.fr-status')).toHaveAttribute('data-focused-sentence', id);
      await reopened.getByRole('button', { name: '返回文献库' }).click();
    }
  } finally { if (app.process().exitCode === null) await app.close(); rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
});
test('M1 performance: 1000-page first paint ≤ 3 seconds, ten-second scrolling ≥ 55 fps', async () => {
  test.setTimeout(90_000);
  const dir = mkdtempSync(join(tmpdir(), 'fr-perf-e2e-')), source = join(dir, 'large.pdf'); writePdf(source, 1000);
  const app = await launch(join(dir, 'user'));
  try {
    const page = await app.firstWindow(); await importPdf(app, page, source);
    const start = performance.now(); await page.locator('.fr-document-open').click();
    await expect(page.locator('[data-page="1"] [data-sentence-id]').first()).toBeVisible();
    const firstPaintMs = performance.now() - start;
    const fps = await page.evaluate(async () => {
      const root = document.querySelector('.fr-reader-area'); if (!root) throw new Error('Missing reader');
      return new Promise<number>((resolve) => { const start = performance.now(); let frames = 0;
        const frame = () => { frames++; root.scrollTop += 8;
          if (performance.now() - start < 10_000) requestAnimationFrame(frame); else resolve(frames * 1000 / (performance.now() - start)); };
        requestAnimationFrame(frame); });
    });
    const measurement = JSON.stringify({ firstPaintMs, fps, pages: 1000, platform: process.platform,
      packaged: process.env['FR_PACKAGED'] === '1', arch: process.arch, os: release(),
      cpu: cpus()[0]?.model, logicalCpus: cpus().length, memoryBytes: totalmem(),
      versions: await app.evaluate(() => process.versions) });
    const evidence = test.info().outputPath('performance.json'); writeFileSync(evidence, measurement);
    await test.info().attach('performance', { path: evidence, contentType: 'application/json' });
    expect(firstPaintMs).toBeLessThanOrEqual(3000); expect(fps).toBeGreaterThanOrEqual(55);
    expect(await page.locator('canvas').count()).toBeLessThanOrEqual(5);
  } finally { await app.close(); rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
});
