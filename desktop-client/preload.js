const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('desktopBridge', {
    appVersion: '0.1.0',
});
