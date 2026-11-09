import { app, BrowserWindow, dialog, ipcMain, session } from 'electron'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { startBackend, type RunningBackend } from './backend'

// electron-vite sets this only under `electron-vite dev`.
const devUrl = process.env.ELECTRON_RENDERER_URL
const rendererIndex = join(__dirname, '../renderer/index.html')

// Where the app itself lives; any navigation elsewhere is treated as hostile.
function isAppUrl(url: string): boolean {
  try {
    if (devUrl) return new URL(url).origin === new URL(devUrl).origin
    return url.split(/[?#]/)[0] === pathToFileURL(rendererIndex).href
  } catch {
    return false
  }
}

let backend: RunningBackend | undefined

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  })

  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  const blockForeignNavigation = (event: Electron.Event, url: string): void => {
    if (!isAppUrl(url)) event.preventDefault()
  }
  win.webContents.on('will-navigate', blockForeignNavigation)
  win.webContents.on('will-redirect', blockForeignNavigation)

  if (devUrl) void win.loadURL(devUrl)
  else void win.loadFile(rendererIndex)
}

async function boot(): Promise<void> {
  // The app needs no camera, mic, geolocation, notifications etc.; deny them all, so
  // even a compromised renderer cannot obtain them.
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false))
  session.defaultSession.setPermissionCheckHandler(() => false)
  try {
    backend = await startBackend({
      backendDir: process.env.NOTE_TAKER_BACKEND_DIR ?? resolve(__dirname, '../../../backend'),
      dataDir: process.env.NOTE_TAKER_DATA_DIR ?? app.getPath('userData')
    })
  } catch (err) {
    // Also to the terminal: the dialog text is gone once dismissed.
    console.error('note-taker: backend failed to start:', (err as Error).message)
    dialog.showErrorBox('Note Taker could not start its backend', (err as Error).message)
    app.quit()
    return
  }

  const { baseUrl, token } = backend
  ipcMain.handle('backend:config', (event) => {
    // Only our own page may learn the token, never a frame that navigated elsewhere.
    if (!isAppUrl(event.senderFrame?.url ?? '')) throw new Error('forbidden')
    return { baseUrl, token }
  })
  createWindow()
}

// Quit waits for the backend to stop; the flag stops the second quit from looping.
let stopped = false
app.on('before-quit', (event) => {
  if (stopped || !backend) return
  event.preventDefault()
  void backend.stop().finally(() => {
    stopped = true
    app.quit()
  })
})

app.on('window-all-closed', () => app.quit())

void app.whenReady().then(boot)
