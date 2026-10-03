import { test, expect } from '@playwright/test';
import { launchElectron } from './electron-app';
import { resolve } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';

test('E1 M1 offline library: bilingual, sandboxed, no ambient privilege', async () => {
  const userData = await mkdtemp(resolve(tmpdir(), 'freeread-e2e-'));
  const app = await launchElectron(userData);
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole('heading', { name: '文献库', exact: true })).toBeVisible();
    expect(await page.evaluate(() => performance.getEntriesByType('resource')
      .some((entry) => /\/ReaderView-[^/]+\.js/.test(entry.name)))).toBe(false);
    await page.getByRole('button', { name: 'English' }).click();
    await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
    expect(await page.locator('html').getAttribute('lang')).toBe('en');
    const privilege = await page.evaluate(() => ({
      require: typeof Reflect.get(window, 'require'),
      process: typeof Reflect.get(window, 'process'),
      bridge: typeof window.fr, genericInvoke: Reflect.has(window.fr, 'invoke'),
      methods: Object.keys(window.fr.app),
    }));
    expect(privilege.require).toBe('undefined');
    expect(privilege.process).toBe('undefined');
    expect(privilege.bridge).toBe('object');
    expect(privilege.genericInvoke).toBe(false);
    expect(privilege.methods).toContain('getCapabilities');
    expect(await app.evaluate(({ app }) => app.commandLine.hasSwitch('no-sandbox'))).toBe(false);
    expect(await app.evaluate(({ BrowserWindow }) => {
      const preferences = BrowserWindow.getAllWindows()[0]?.webContents.getLastWebPreferences();
      return { sandbox: preferences?.sandbox, nodeIntegration: preferences?.nodeIntegration,
        contextIsolation: preferences?.contextIsolation };
    })).toEqual({ sandbox: true, nodeIntegration: false, contextIsolation: true });
    await page.screenshot({ path: 'test-results/m1-library.png', fullPage: true });
    await app.evaluate(({ session }) => session.defaultSession.webRequest.onBeforeRequest(
      { urls: ['http://*/*', 'https://*/*', 'file://*/*ReaderView-*.js'] },
      (_details, callback) => callback({ cancel: true })));
    await page.evaluate(() => { location.hash = '/reader/unavailable'; });
    await expect(page.getByRole('alert')).toContainText('The view failed');
    await page.getByRole('button', { name: 'Back to library', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
  } finally {
    await app.close();
    await rm(userData, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
});
