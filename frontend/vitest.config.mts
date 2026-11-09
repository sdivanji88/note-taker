import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['tests/setup.ts'],
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    // Playwright specs live in e2e/ and run under `playwright test`.
    exclude: ['e2e/**', 'node_modules/**']
  }
})
