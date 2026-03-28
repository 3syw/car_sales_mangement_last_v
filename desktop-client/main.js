const { app, BrowserWindow, shell, nativeTheme } = require('electron');
const path = require('path');

nativeTheme.themeSource = 'light';

function normalizeBaseUrl(rawUrl) {
    return String(rawUrl || 'http://127.0.0.1:8102')
        .trim()
        .replace(/\/$/, '');
}

function resolveInitialUrl() {
    const baseUrl = normalizeBaseUrl(process.env.DESKTOP_WEB_URL || 'http://127.0.0.1:8102');
    const initialPath = process.env.DESKTOP_WEB_PATH || '/login/';
    return `${baseUrl}${initialPath.startsWith('/') ? initialPath : `/${initialPath}`}`;
}

function createMainWindow() {
    const mainWindow = new BrowserWindow({
        width: 1480,
        height: 940,
        minWidth: 1220,
        minHeight: 760,
        backgroundColor: '#0f141c',
        autoHideMenuBar: true,
        show: false,
        webPreferences: {
            contextIsolation: true,
            nodeIntegration: false,
            preload: path.join(__dirname, 'preload.js'),
        },
    });

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
    });

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        shell.openExternal(url);
        return { action: 'deny' };
    });

    mainWindow.webContents.on('did-fail-load', () => {
        mainWindow.loadFile(path.join(__dirname, 'src', 'offline.html'));
    });

    mainWindow.loadURL(resolveInitialUrl());
}

app.whenReady().then(() => {
    createMainWindow();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createMainWindow();
        }
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
