import { app, BrowserWindow, session } from 'electron';
import { join } from 'node:path';
import { toAppError } from '@freeread/core';

if (process.argv.includes('--fr-benchmark')) process.stdout.write(JSON.stringify({ event: 'app.main' }) + '\n');

async function createWindow(): Promise<void> {
  const window = new BrowserWindow({
    width: 1100, height: 760, minWidth: 640, minHeight: 480, show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.once('ready-to-show', () => {
    window.show();
    if (process.argv.includes('--fr-benchmark')) {
      process.stdout.write(JSON.stringify({ event: 'app.ready' }) + '\n');
      app.quit();
    }
  });
  try {
    if (!app.isPackaged && process.env['ELECTRON_RENDERER_URL']) {
      await window.loadURL(process.env['ELECTRON_RENDERER_URL']);
    } else {
      await window.loadFile(join(__dirname, '../renderer/index.html'));
    }
  } catch (cause) {
    console.error(toAppError(cause).toWire());
    app.quit();
  }
}

app.whenReady().then(async () => {
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] },
    (details, callback) => {
      const devUrl = process.env['ELECTRON_RENDERER_URL'];
      callback({ cancel: app.isPackaged || !devUrl || new URL(details.url).origin !== new URL(devUrl).origin });
    });
  await createWindow();
}).catch((cause: unknown) => {
  console.error(toAppError(cause).toWire());
  app.quit();
});
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
