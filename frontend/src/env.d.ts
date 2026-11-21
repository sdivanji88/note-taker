/// <reference types="vite/client" />

interface Window {
  // Exposed by electron/preload/index.ts; the renderer's only link to the main process.
  noteTaker: { getConfig: () => Promise<{ baseUrl: string; token: string }> }
}
