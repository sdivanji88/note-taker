import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import Settings from '../src/screens/Settings'
import { ApiError } from '../src/api/types'
import type { Health, Settings as SettingsT } from '../src/api/types'
import { fakeClient, renderWith } from './helpers'

const base: SettingsT = {
  notes_repo: { remote_url: 'git@github.com:me/notes.git', branch: 'main', local_path: null, books_dir: 'books' },
  extractor: {
    kind: 'ollama',
    ollama: { base_url: 'http://localhost:11434', model: 'llava' },
    tesseract: { hsv_low: [20, 80, 80], hsv_high: [40, 255, 255], lang: 'eng' },
    concurrency: 1,
    timeout_s: 180
  },
  batches: { expiry_days: 30, warn_days_before: 7 },
  remote_url_has_credentials: false
}
const withUrl = (url: string, creds: boolean): SettingsT => ({
  ...base,
  notes_repo: { ...base.notes_repo, remote_url: url },
  remote_url_has_credentials: creds
})
const okHealth: Health = {
  extractor: { kind: 'ollama', ok: true, detail: 'ready' },
  repo: { cloned: true, dirty: false, path: '/clone' },
  remote: { ok: true, detail: 'ok' }
}
const CRED_NOTICE = /This URL contains credentials\. The app doesn't need them/

function setup(over: Record<string, unknown> = {}, props: { onBack?: () => void } = {}) {
  const f = fakeClient({
    getSettings: vi.fn().mockResolvedValue(base),
    putSettings: vi.fn().mockImplementation(async (s: SettingsT) => s),
    connectRepo: vi.fn().mockResolvedValue({ cloned: true, dirty: false, path: '/clone' }),
    getHealth: vi.fn().mockResolvedValue(okHealth),
    ...over
  })
  renderWith(f.client, <Settings onBack={props.onBack ?? (() => {})} />)
  return f.client
}
const field = (name: RegExp) => screen.findByLabelText(name) as Promise<HTMLInputElement>
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } })
const sent = (c: { putSettings: unknown }) => vi.mocked(c.putSettings as (s: SettingsT) => unknown).mock.calls[0][0] as SettingsT
const saveBtn = () => screen.getByRole('button', { name: /^save$/i })

describe('Settings', () => {
  it('loads and saves settings', async () => {
    const client = setup()
    expect(await field(/^branch$/i)).toHaveValue('main')
    expect(screen.getByLabelText(/model/i)).toHaveValue('llava')
    expect(saveBtn()).toBeDisabled()
    type(screen.getByLabelText(/expiry days/i), '14')
    expect(saveBtn()).toBeEnabled()
    fireEvent.click(saveBtn())
    await waitFor(() => expect(client.putSettings).toHaveBeenCalledTimes(1))
    const body = sent(client)
    expect(body.batches).toEqual({ expiry_days: 14, warn_days_before: 7 })
    expect(body.notes_repo.branch).toBe('main')
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(saveBtn()).toBeDisabled()
    expect(client.getHealth).toHaveBeenCalledTimes(2)
  })

  it('rejects expiry days below 1 without sending anything', async () => {
    const client = setup()
    type(await field(/expiry days/i), '0')
    expect(screen.getByText(/expiry days must be at least 1/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/expiry days/i)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText(/expiry days/i)).toHaveAccessibleDescription(/at least 1/i)
    expect(saveBtn()).toBeDisabled()
    fireEvent.click(saveBtn())
    expect(client.putSettings).not.toHaveBeenCalled()
  })

  it('mirrors the server bounds for timeout and concurrency', async () => {
    setup()
    type(await field(/timeout/i), '3601')
    expect(screen.getByText(/timeout must be between 1 and 3600/i)).toBeInTheDocument()
    type(screen.getByLabelText(/concurrency/i), '5')
    expect(screen.getByText(/concurrency must be between 1 and 4/i)).toBeInTheDocument()
    expect(saveBtn()).toBeDisabled()
  })

  it('notes that concurrency and timeout apply after a restart', async () => {
    setup()
    await field(/concurrency/i)
    expect(screen.getAllByText(/take effect after restarting the app/i).length).toBe(2)
  })

  it('health panel shows model-not-pulled detail verbatim', async () => {
    setup({
      getHealth: vi.fn().mockResolvedValue({
        ...okHealth,
        extractor: { kind: 'ollama', ok: false, detail: 'model not pulled (run: ollama pull llava)' }
      })
    })
    expect(await screen.findByText('model not pulled (run: ollama pull llava)')).toBeInTheDocument()
    expect(screen.getByText(/not ok/i)).toBeInTheDocument()
  })

  it('Re-check refetches health', async () => {
    const client = setup()
    await screen.findByText('ready')
    fireEvent.click(screen.getByRole('button', { name: /re-check/i }))
    await waitFor(() => expect(client.getHealth).toHaveBeenCalledTimes(2))
  })

  it('connect repo shows git stderr verbatim on failure', async () => {
    const stderr = "fatal: repository '/nope' does not exist"
    const client = setup({
      connectRepo: vi.fn().mockRejectedValue(new ApiError(400, 'git_failed', stderr))
    })
    await field(/remote url/i)
    fireEvent.click(screen.getByRole('button', { name: /connect repo/i }))
    const out = await screen.findByText(stderr)
    expect(out.tagName).toBe('PRE')
    expect(screen.getByText(/git_failed/)).toBeInTheDocument()
    expect(client.connectRepo).toHaveBeenCalledTimes(1)
  })

  it('connect repo success shows confirmation and refreshes health', async () => {
    const client = setup()
    await field(/remote url/i)
    fireEvent.click(screen.getByRole('button', { name: /connect repo/i }))
    expect(await screen.findByText(/repo connected/i)).toBeInTheDocument()
    await waitFor(() => expect(client.getHealth).toHaveBeenCalledTimes(2))
  })

  it('connect is disabled while in flight so it cannot double submit', async () => {
    let resolve!: (v: unknown) => void
    const client = setup({ connectRepo: vi.fn(() => new Promise((r) => (resolve = r))) })
    await field(/remote url/i)
    const btn = screen.getByRole('button', { name: /connect repo/i })
    fireEvent.click(btn)
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    expect(client.connectRepo).toHaveBeenCalledTimes(1)
    resolve({ cloned: true, dirty: false, path: '/c' })
    await screen.findByText(/repo connected/i)
    expect(btn).toBeEnabled()
  })

  it('connect is disabled with a hint while there are unsaved changes', async () => {
    setup()
    type(await field(/^branch$/i), 'dev')
    const btn = screen.getByRole('button', { name: /connect repo/i })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('title', 'Save your changes first')
  })

  it('sends a masked URL back unchanged when untouched', async () => {
    const masked = 'https://***@github.com/me/notes.git'
    const client = setup({ getSettings: vi.fn().mockResolvedValue(withUrl(masked, true)) })
    expect(await field(/remote url/i)).toHaveValue(masked)
    type(screen.getByLabelText(/^branch$/i), 'dev')
    fireEvent.click(saveBtn())
    await waitFor(() => expect(client.putSettings).toHaveBeenCalled())
    expect((sent(client)).notes_repo.remote_url).toBe(masked)
  })

  it('trims the repo fields before saving', async () => {
    const client = setup()
    type(await field(/remote url/i), '  git@github.com:me/x.git ')
    type(screen.getByLabelText(/^branch$/i), ' dev ')
    type(screen.getByLabelText(/existing clone/i), ' /Users/me/notes ')
    type(screen.getByLabelText(/books folder/i), ' books ')
    fireEvent.click(saveBtn())
    await waitFor(() => expect(client.putSettings).toHaveBeenCalled())
    expect(sent(client).notes_repo).toEqual({
      remote_url: 'git@github.com:me/x.git', branch: 'dev', local_path: '/Users/me/notes', books_dir: 'books'
    })
  })

  it('sends a typed URL in place of the masked one', async () => {
    const client = setup({
      getSettings: vi.fn().mockResolvedValue(withUrl('https://***@github.com/me/notes.git', true))
    })
    type(await field(/remote url/i), 'git@github.com:me/other.git')
    fireEvent.click(saveBtn())
    await waitFor(() => expect(client.putSettings).toHaveBeenCalled())
    expect((sent(client)).notes_repo.remote_url).toBe('git@github.com:me/other.git')
  })

  it('shows the credentials notice for a masked-with-credentials URL', async () => {
    setup({ getSettings: vi.fn().mockResolvedValue(withUrl('https://***@github.com/me/n.git', true)) })
    expect(await screen.findByText(CRED_NOTICE)).toBeInTheDocument()
  })

  it('shows no credentials notice for a clean URL', async () => {
    setup()
    await field(/remote url/i)
    expect(screen.queryByText(CRED_NOTICE)).toBeNull()
  })

  it('shows the credentials notice for a typed URL with a token and never echoes the token', async () => {
    setup({ putSettings: vi.fn().mockRejectedValue(new ApiError(500, 'boom', 'server said no')) })
    type(await field(/remote url/i), 'https://user:ghp_SECRET@github.com/me/n.git')
    expect(screen.getByText(CRED_NOTICE)).toBeInTheDocument()
    fireEvent.click(saveBtn())
    await screen.findByText('server said no')
    expect(screen.queryByText(/ghp_SECRET/)).toBeNull()
    // The input legitimately holds what the user typed; nothing else may.
    const outside = document.body.textContent ?? ''
    expect(outside).not.toContain('ghp_SECRET')
  })

  it('shows a server 422 message verbatim as text', async () => {
    setup({
      putSettings: vi
        .fn()
        .mockRejectedValue(new ApiError(422, 'invalid_settings', 'notes_repo.branch is not a valid branch name'))
    })
    type(await field(/^branch$/i), 'a b')
    fireEvent.click(saveBtn())
    expect(await screen.findByRole('alert')).toHaveTextContent('notes_repo.branch is not a valid branch name')
    expect(saveBtn()).toBeEnabled()
  })

  it('maps a network error to a friendly message', async () => {
    setup({ putSettings: vi.fn().mockRejectedValue(new ApiError(0, 'network_error', 'fetch failed')) })
    type(await field(/expiry days/i), '5')
    fireEvent.click(saveBtn())
    expect(await screen.findByRole('alert')).toHaveTextContent("Can't reach the backend.")
  })

  it('focuses the first invalid field when a save is refused', async () => {
    setup()
    type(await field(/timeout/i), '0')
    type(screen.getByLabelText(/expiry days/i), '0')
    fireEvent.click(saveBtn())
    // Save is disabled while invalid, so Enter in the form is the route to a refused save.
    fireEvent.submit(screen.getByRole('form', { name: /settings/i }))
    expect(screen.getByLabelText(/timeout/i)).toHaveFocus()
  })

  it('renders hostile health and stderr text literally', async () => {
    const hostile = '<img src=x onerror=alert(1)>'
    setup({
      getHealth: vi.fn().mockResolvedValue({ ...okHealth, remote: { ok: false, detail: hostile } }),
      connectRepo: vi.fn().mockRejectedValue(new ApiError(400, 'git_failed', hostile + ' stderr'))
    })
    expect(await screen.findByText(hostile)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /connect repo/i }))
    expect(await screen.findByText(hostile + ' stderr')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('Back with unsaved edits asks first; Keep editing stays', async () => {
    const onBack = vi.fn()
    setup({}, { onBack })
    type(await field(/expiry days/i), '5')
    fireEvent.click(screen.getByRole('button', { name: /back/i }))
    expect(screen.getByText('Discard unsaved settings changes?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(onBack).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByLabelText(/expiry days/i)).toHaveValue(5)
  })

  it('Back with unsaved edits leaves on Discard', async () => {
    const onBack = vi.fn()
    setup({}, { onBack })
    type(await field(/expiry days/i), '5')
    fireEvent.click(screen.getByRole('button', { name: /back/i }))
    fireEvent.click(screen.getByRole('button', { name: /^discard$/i }))
    expect(onBack).toHaveBeenCalled()
  })

  it('Back with no edits leaves immediately', async () => {
    const onBack = vi.fn()
    setup({}, { onBack })
    await field(/expiry days/i)
    fireEvent.click(screen.getByRole('button', { name: /back/i }))
    expect(onBack).toHaveBeenCalled()
  })
})
