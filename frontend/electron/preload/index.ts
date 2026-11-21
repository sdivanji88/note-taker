import { contextBridge, ipcRenderer } from 'electron'

// The only bridge into the renderer. No raw ipcRenderer: the renderer displays book
// text and talks to a localhost API, so it gets one narrow, read-only capability.
contextBridge.exposeInMainWorld('noteTaker', {
  getConfig: (): Promise<{ baseUrl: string; token: string }> => ipcRenderer.invoke('backend:config')
})
