import { app, BrowserWindow, ipcMain, nativeTheme, session } from 'electron';
import { createHash } from 'node:crypto';
import { unlinkSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// needed in case process is undefined under Linux
const platform = process.platform || os.platform();

function getLegacyKioskMac(): string | undefined {
  const interfaces = os.networkInterfaces();
  const interfacePrefix =
    os.platform() === 'darwin'
      ? 'en'
      : os.platform() === 'win32'
        ? null
        : 'eth';

  if (interfacePrefix) {
    for (let index = -1; index < 8; index += 1) {
      const interfaceName = `${interfacePrefix}${index >= 0 ? index : ''}`;
      const address = interfaces[interfaceName]?.find(
        (item) => item.family === 'IPv4' && Boolean(item.mac),
      );

      if (address?.mac) {
        return address.mac;
      }
    }
  }

  for (const addresses of Object.values(interfaces)) {
    const address = addresses?.find(
      (item) =>
        item.family === 'IPv4' &&
        !item.address.startsWith('127.') &&
        Boolean(item.mac),
    );

    if (address?.mac) {
      return address.mac;
    }
  }

  return undefined;
}

function getKioskIdentity(): string {
  const macAddress = getLegacyKioskMac();

  if (!macAddress) {
    throw new Error(
      'Unable to derive a kiosk identity from a network interface',
    );
  }

  return createHash('sha256').update(macAddress).digest('hex');
}

try {
  if (platform === 'win32' && nativeTheme.shouldUseDarkColors === true) {
    unlinkSync(path.join(app.getPath('userData'), 'DevTools Extensions'));
  }
} catch {}

let mainWindow: BrowserWindow | undefined;

ipcMain.handle('kiosk:get-identity', (event) => {
  if (event.sender.id !== mainWindow?.webContents.id) {
    throw new Error('Kiosk identity is only available to the main window');
  }

  return getKioskIdentity();
});

function createWindow() {
  /**
   * Initial window options
   */
  mainWindow = new BrowserWindow({
    icon: path.resolve(__dirname, 'icons/icon.png'), // tray icon
    fullscreen: process.env.NODE_ENV !== 'Development',
    useContentSize: true,
    webPreferences: {
      contextIsolation: true,
      // More info: https://v2.quasar.dev/quasar-cli-vite/developing-electron-apps/electron-preload-script
      preload: path.resolve(__dirname, process.env.QUASAR_ELECTRON_PRELOAD),
    },
  });

  // Set the SameSite attribute to "None" for all cookies
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.responseHeaders && details.responseHeaders['set-cookie']) {
      details.responseHeaders['set-cookie'] = details.responseHeaders[
        'set-cookie'
      ].map((cookie: string) => {
        return cookie + '; SameSite=None; Secure';
      });
    }
    callback({ cancel: false, responseHeaders: details.responseHeaders });
  });

  mainWindow.loadURL(process.env.APP_URL);

  if (process.env.DEBUGGING) {
    // if on DEV or Production with debug enabled
    mainWindow.webContents.openDevTools();
  } else {
    // TODO: comment out if you want to block access to dev tools in production
    // mainWindow.webContents.on('devtools-opened', () => {
    //   mainWindow?.webContents.closeDevTools();
    // });
  }

  mainWindow.on('closed', () => {
    mainWindow = undefined;
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === undefined) {
    createWindow();
  }
});
