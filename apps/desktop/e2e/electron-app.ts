import { _electron as electron, expect } from '@playwright/test';
import { resolve } from 'node:path';

export async function launchElectron(userData: string) {
  const env = { ...process.env, ELECTRON_RENDERER_URL: '' }; delete env['ELECTRON_RUN_AS_NODE'];
  const packaged = env['FR_PACKAGED'] === '1';
  const executablePath = resolve('artifacts', process.platform === 'win32' ? 'win-unpacked/FreeRead.exe'
    : process.platform === 'darwin' ? `${process.arch === 'arm64' ? 'mac-arm64' : 'mac'}/FreeRead.app/Contents/MacOS/FreeRead`
    : 'linux-unpacked/freeread');
  const app = await electron.launch({ chromiumSandbox: true, env,
    args: [...(packaged ? [] : [resolve('apps/desktop')]), `--user-data-dir=${userData}`],
    ...(packaged ? { executablePath } : {}) });
  app.process().stderr?.on('data', (bytes: Buffer) => console.error(bytes.toString()));
  expect(await app.evaluate(({ app }) => app.isPackaged)).toBe(packaged);
  return app;
}
