import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('memberMatters', {
  getKioskIdentity: (): Promise<string> =>
    ipcRenderer.invoke('kiosk:get-identity'),
});
