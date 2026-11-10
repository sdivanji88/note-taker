import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'

// Vite's dev server needs an inline React-refresh preamble, injected styles and a
// websocket for HMR; the production CSP in index.html allows none of that. Applied to
// `serve` only, so built output keeps the strict policy.
const relaxCspForDevServer = {
  name: 'relax-csp-for-dev-server',
  apply: 'serve' as const,
  transformIndexHtml: (html: string) =>
    html
      .replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
      .replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
      .replace("connect-src 'self'", "connect-src 'self' ws://localhost:5173")
}

export default defineConfig({
  main: {
    build: { rollupOptions: { input: { index: resolve(__dirname, 'electron/main/index.ts') } } }
  },
  preload: {
    build: { rollupOptions: { input: { index: resolve(__dirname, 'electron/preload/index.ts') } } }
  },
  renderer: {
    // index.html lives at the frontend root so src/ is purely the React app.
    root: __dirname,
    build: { rollupOptions: { input: { index: resolve(__dirname, 'index.html') } } },
    // Fixed so the origin stays http://localhost:5173, the one the backend's CORS allows.
    server: { port: 5173, strictPort: true },
    plugins: [react(), relaxCspForDevServer]
  }
})
