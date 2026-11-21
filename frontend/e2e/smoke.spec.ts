import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { existsSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import {
  createSandbox,
  gitBare,
  hasTesseract,
  highlightedTextPng,
  killLeftoverBackends,
  writeSettings,
  type Sandbox
} from './helpers'

const FRONTEND = resolve(__dirname, '..')
const BUILT_MAIN = join(FRONTEND, 'out/main/index.js')

let sb: Sandbox
let app: ElectronApplication | undefined

test.beforeAll(() => {
  // Testing a stale or missing build would prove nothing about the app users run.
  if (!existsSync(BUILT_MAIN))
    throw new Error(`${BUILT_MAIN} is missing. Run "npm run build" in frontend/ before the e2e tests.`)
})

test.beforeEach(() => {
  sb = createSandbox()
})

test.afterEach(async () => {
  // A crashed or hung close must not leave a backend or a temp dir behind.
  try {
    await app?.close()
  } catch {
    // Already closed or crashed; the sweep below catches whatever survived.
  }
  app = undefined
  // The backend exits on stdin EOF shortly after the app quits.
  await new Promise((r) => setTimeout(r, 1500))
  const leaked = killLeftoverBackends(sb)
  const { rmSync } = await import('node:fs')
  rmSync(sb.root, { recursive: true, force: true })
  expect(leaked, 'a note_taker backend outlived the app').toEqual([])
})

async function launch(): Promise<Page> {
  // Electron's own profile (caches, cookies) ignores $HOME on macOS, so it is redirected
  // explicitly; otherwise every run would write into the developer's real app profile.
  app = await electron.launch({
    args: ['.', `--user-data-dir=${join(sb.root, 'electron-profile')}`],
    cwd: FRONTEND,
    env: sb.env
  })
  const page = await app.firstWindow()
  await expect(page.getByRole('heading', { name: 'Note Taker' })).toBeVisible({ timeout: 60_000 })
  return page
}

async function connectRepo(page: Page, { fillUrl }: { fillUrl: boolean }): Promise<void> {
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  if (fillUrl) {
    await page.getByLabel('Remote URL').fill(sb.bare)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  }
  await page.getByRole('button', { name: 'Connect repo' }).click()
  await expect(page.getByText('Repo connected.')).toBeVisible()
  await page.getByRole('button', { name: '← Back' }).click()
}

async function newBatchWithBook(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'New batch', exact: true }).click()
  await page.getByLabel('Book for all').selectOption({ label: '+ New book…' })
  const form = page.getByRole('form', { name: 'New book' })
  await form.getByLabel('Title').fill('Permutation City')
  await form.getByLabel('Kind').selectOption('fiction')
  await form.getByRole('button', { name: 'Create book' }).click()
  await expect(page.getByLabel('Book for all')).toHaveValue('permutation-city')
}

async function pushAndVerify(page: Page, expectedTexts: RegExp[]): Promise<void> {
  const before = Number(gitBare(sb, ['rev-list', '--count', 'main']).trim())
  await page.getByRole('button', { name: 'Push all approved (2)' }).click()
  await expect(page.getByRole('status', { name: 'Push result' })).toContainText('Pushed 2 highlights')

  const file = gitBare(sb, ['show', 'main:books/permutation-city.md'])
  expect(file).toMatch(/^---\n[\s\S]*?\n---\n/)
  expect(file).toContain('# Permutation City')
  expect(file.match(/^## /gm)).toHaveLength(2)
  const markers = file.match(/<!-- nt:highlight=\S+ -->/g) ?? []
  expect(new Set(markers).size).toBe(2)
  for (const t of expectedTexts) expect(file).toMatch(t)

  expect(Number(gitBare(sb, ['rev-list', '--count', 'main']).trim())).toBe(before + 1)
  const message = gitBare(sb, ['log', '-1', '--format=%B', 'main'])
  expect(message.startsWith('notes: 2 highlights from Permutation City')).toBe(true)
  expect(message).toContain('Note-Taker-Batch:')

  await page.getByRole('button', { name: '← Batches' }).click()
  await expect(page.getByText('No open batches')).toBeVisible()
  // Pushing deletes the batch folder: only in-progress batches may stay on disk.
  expect(readdirSync(join(sb.dataDir, 'batches'))).toEqual([])
}

test('kindle highlights go from the app to a pushed markdown file', async () => {
  const page = await launch()
  await connectRepo(page, { fillUrl: true })
  await newBatchWithBook(page)

  await page.getByRole('button', { name: 'Add Kindle highlight' }).click()
  await page.getByLabel('Page').fill('163')
  await page.getByLabel('Highlight text').fill('first draft that gets replaced')
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  await page.getByLabel('Highlight text').fill('Memory is the city we rebuild every morning.')
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()

  await page.getByRole('button', { name: 'Add Kindle highlight' }).click()
  await page.getByLabel('Chapter').fill('The Lobian Argument')
  await page.getByLabel('Highlight text').fill('Dreams outlast the dreamer.')
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()

  await pushAndVerify(page, [/Memory is the city we rebuild every morning\./, /Dreams outlast the dreamer\./])
})

test.describe('photo path', () => {
  test.skip(!hasTesseract(), 'tesseract is not on PATH (brew install tesseract); photo path needs real OCR')

  test('uploaded photos are OCR-extracted, reviewed and pushed', async () => {
    writeSettings(sb, {
      notes_repo: { remote_url: sb.bare, branch: 'main', local_path: null, books_dir: 'books' },
      extractor: { kind: 'tesseract' }
    })
    const page = await launch()
    await connectRepo(page, { fillUrl: false })
    await newBatchWithBook(page)

    await page.getByLabel('Photo files').setInputFiles([
      { name: 'p1.png', mimeType: 'image/png', buffer: highlightedTextPng('MEMORY IS THE CITY') },
      { name: 'p2.png', mimeType: 'image/png', buffer: highlightedTextPng('DREAMS WILL OUTLAST US') }
    ])
    await expect(page.locator('.badge-ready')).toHaveCount(2, { timeout: 90_000 })

    await page.getByRole('button', { name: /^Review/ }).click()
    await page.getByRole('button', { name: 'Approve', exact: true }).click()
    await page.getByRole('button', { name: 'Approve', exact: true }).click()

    // OCR on synthetic bitmap text is lenient: one distinctive word per page.
    await pushAndVerify(page, [/memory/i, /dreams/i])
  })
})
