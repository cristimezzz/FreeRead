import { test, expect, _electron as electron } from '@playwright/test';
import { resolve } from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';

test('M0 offline shell: bilingual, sandboxed, no ambient privilege', async () => {
  const userData = await mkdtemp(resolve(tmpdir(), 'freeread-e2e-'));
  const environment = { ...process.env, ELECTRON_RENDERER_URL: '' };
  delete environment['ELECTRON_RUN_AS_NODE'];
  const app = await electron.launch({
    chromiumSandbox: true,
    args: [resolve('apps/desktop'), `--user-data-dir=${userData}`],
    env: environment,
  });
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole('heading', { name: '工程骨架已就绪' })).toBeVisible();
    await page.getByRole('button', { name: 'English' }).click();
    await expect(page.getByRole('heading', { name: 'Project skeleton is ready' })).toBeVisible();
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
    await page.screenshot({ path: 'test-results/m0-shell.png', fullPage: true });
  } finally {
    await app.close();
    await rm(userData, { recursive: true, force: true });
  }
});
