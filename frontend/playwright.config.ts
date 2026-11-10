import { defineConfig } from '@playwright/test'

// One Electron app per test and each spawns a real Python backend plus git, so tests
// run serially; the generous timeout covers `uv run` start-up on a cold cache.
export default defineConfig({
  testDir: 'e2e',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  outputDir: 'test-results',
  reporter: [['list']],
  use: { trace: 'retain-on-failure' }
})
