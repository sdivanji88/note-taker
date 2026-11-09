import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import Root from '../src/Root'
import { batch, fakeClient, renderWith, summary } from './helpers'

describe('App routing', () => {
  it('list -> grid -> review placeholder -> back, and settings placeholder', async () => {
    const { client } = fakeClient({
      listBatches: vi.fn().mockResolvedValue([summary('b1')]),
      getBatch: vi.fn().mockResolvedValue(batch([{ ...batch().captures[0] }].slice(1))),
      getSettings: vi.fn().mockResolvedValue({
        notes_repo: { remote_url: '', branch: 'main', local_path: null, books_dir: 'books' },
        extractor: {
          kind: 'tesseract',
          ollama: { base_url: 'http://localhost:11434', model: '' },
          tesseract: { hsv_low: [0, 0, 0], hsv_high: [0, 0, 0], lang: 'eng' },
          concurrency: 1,
          timeout_s: 180
        },
        batches: { expiry_days: 30, warn_days_before: 7 }
      })
    })
    renderWith(client, <App />)
    fireEvent.click(await screen.findByRole('button', { name: /resume/i }))
    await screen.findByRole('button', { name: /add kindle highlight/i })
    fireEvent.click(screen.getByRole('button', { name: /← batches/i }))
    fireEvent.click(await screen.findByRole('button', { name: /^settings$/i }))
    expect(await screen.findByRole('heading', { name: /settings/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /back/i }))
    await screen.findByRole('button', { name: /new batch/i })
  })
})

describe('Root', () => {
  it('shows a plain error without the token when config cannot be loaded', async () => {
    render(<Root getConfig={() => Promise.reject(new Error('ipc failed'))} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('ipc failed')
  })

  it('shows an error when the backend health check fails, without the token', async () => {
    const { client } = fakeClient({ getHealth: vi.fn().mockRejectedValue(new Error('could not reach the Note Taker backend')) })
    render(<Root getConfig={async () => ({ baseUrl: 'http://127.0.0.1:1', token: 'sekrit' })} makeClient={() => client} />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('could not reach the Note Taker backend')
    expect(alert).not.toHaveTextContent('sekrit')
  })

  it('renders the app once the backend answers', async () => {
    const { client } = fakeClient()
    render(<Root getConfig={async () => ({ baseUrl: 'http://127.0.0.1:1', token: 't' })} makeClient={() => client} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /new batch/i })).toBeInTheDocument())
  })
})
