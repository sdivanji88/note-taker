import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createClient } from '../src/api/client'
import { ApiError } from '../src/api/types'

const cfg = { baseUrl: 'http://127.0.0.1:9999', token: 'sekrit-token' }

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

let fetchMock: ReturnType<typeof vi.fn>
beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('createClient', () => {
  it('sends token header', async () => {
    fetchMock.mockResolvedValue(reply(200, []))
    await createClient(cfg).listBooks()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:9999/books')
    expect(new Headers(init.headers).get('X-Session-Token')).toBe('sekrit-token')
    expect(url).not.toContain('token')
  })

  it('throws ApiError with backend code on 409', async () => {
    fetchMock.mockResolvedValue(
      reply(409, { error: { code: 'dirty_repo', message: 'repo has local changes' } })
    )
    const err = await createClient(cfg).push('b1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 409, code: 'dirty_repo', message: 'repo has local changes' })
  })

  it('ping probes the cheap readiness route with the token', async () => {
    fetchMock.mockResolvedValue(reply(200, { ok: true }))
    expect(await createClient(cfg).ping()).toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:9999/ping')
    expect(new Headers(init.headers).get('X-Session-Token')).toBe('sekrit-token')
  })

  it('imageUrl includes token query', () => {
    const url = new URL(createClient(cfg).imageUrl('c1'))
    expect(url.pathname).toBe('/captures/c1/image')
    expect(url.searchParams.get('token')).toBe('sekrit-token')
  })

  it('uploadPhotos posts multipart with files field', async () => {
    fetchMock.mockResolvedValue(reply(200, { created: [], rejected: [] }))
    const a = new File(['a'], 'a.jpg', { type: 'image/jpeg' })
    const b = new File(['b'], 'b.jpg', { type: 'image/jpeg' })
    await createClient(cfg).uploadPhotos('b1', [a, b])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:9999/batches/b1/captures')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).getAll('files').map((f) => (f as File).name)).toEqual([
      'a.jpg',
      'b.jpg'
    ])
    // fetch must set the multipart boundary itself.
    expect(new Headers(init.headers).has('Content-Type')).toBe(false)
  })

  it('turns a network failure into ApiError status 0', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const err = await createClient(cfg).getHealth().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 0, code: 'network_error' })
  })

  it('falls back to the status text when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<html>boom</html>', { status: 502, statusText: 'Bad Gateway' }))
    const err = await createClient(cfg).getSettings().catch((e) => e)
    expect(err).toMatchObject({ status: 502, code: 'http_error', message: 'Bad Gateway' })
  })

  it('never puts the token in an ApiError message', async () => {
    fetchMock.mockRejectedValue(new TypeError(`connect failed ${cfg.baseUrl}?token=${cfg.token}`))
    const net = await createClient(cfg).getHealth().catch((e) => e)
    expect(net.message).not.toContain(cfg.token)
    fetchMock.mockResolvedValue(reply(401, { error: { code: 'unauthorized', message: `bad ${cfg.token}` } }))
    const http = await createClient(cfg).getHealth().catch((e) => e)
    expect(http.message).not.toContain(cfg.token)
  })

  it('sends JSON bodies and resolves 204 to undefined', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(createClient(cfg).deleteBatch('b1')).resolves.toBeUndefined()
    fetchMock.mockResolvedValue(reply(200, {}))
    await createClient(cfg).patchCapture('c1', { status: 'approved' })
    const [, init] = fetchMock.mock.calls[1]
    expect(init.method).toBe('PATCH')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ status: 'approved' })
  })

  it('retryCapture sends the chosen extractor', async () => {
    fetchMock.mockResolvedValue(reply(200, {}))
    await createClient(cfg).retryCapture('c1', 'tesseract')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:9999/captures/c1/retry')
    expect(JSON.parse(init.body)).toEqual({ extractor: 'tesseract' })
  })
})

describe('subscribe', () => {
  class FakeEventSource {
    static last: FakeEventSource
    listeners = new Map<string, (e: MessageEvent) => void>()
    closed = false
    // EventSource.CLOSED is 2; the real constant is not available under jsdom-less stubs.
    static CLOSED = 2
    readyState = 0
    onopen: (() => void) | null = null
    onerror: (() => void) | null = null
    constructor(public url: string) {
      FakeEventSource.last = this
    }
    addEventListener(type: string, fn: (e: MessageEvent) => void) {
      this.listeners.set(type, fn)
    }
    close() {
      this.closed = true
    }
  }
  beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource))

  it('uses ?token, parses typed events and closes on unsubscribe', () => {
    const onEvent = vi.fn()
    const stop = createClient(cfg).subscribe('b1', onEvent)
    const es = FakeEventSource.last
    const url = new URL(es.url)
    expect(url.pathname).toBe('/batches/b1/events')
    expect(url.searchParams.get('token')).toBe('sekrit-token')

    const data = { capture_id: 'c1', status: 'ready', error: null }
    es.listeners.get('capture.status_changed')!({ data: JSON.stringify(data) } as MessageEvent)
    expect(onEvent).toHaveBeenCalledWith({ type: 'capture.status_changed', data })

    stop()
    expect(es.closed).toBe(true)
  })

  it('reports live / reconnecting / closed through onState', () => {
    const states: string[] = []
    createClient(cfg).subscribe('b1', vi.fn(), (st) => states.push(st))
    const es = FakeEventSource.last
    es.onopen?.()
    es.readyState = 0 // browser is retrying
    es.onerror?.()
    es.onopen?.()
    es.readyState = FakeEventSource.CLOSED // browser gave up
    es.onerror?.()
    expect(states).toEqual(['live', 'reconnecting', 'live', 'closed'])
  })

  it('works without an onState callback', () => {
    createClient(cfg).subscribe('b1', vi.fn())
    const es = FakeEventSource.last
    expect(() => {
      es.onopen?.()
      es.onerror?.()
    }).not.toThrow()
  })

  it('drops a malformed frame without throwing, logging its payload, or losing later frames', () => {
    const onEvent = vi.fn()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    createClient(cfg).subscribe('b1', onEvent)
    const handler = FakeEventSource.last.listeners.get('capture.extracted')!
    expect(() => handler({ data: '{not json: secret-payload' } as MessageEvent)).not.toThrow()
    expect(onEvent).not.toHaveBeenCalled()
    expect(warn.mock.calls.flat().join(' ')).toContain('capture.extracted')
    expect(warn.mock.calls.flat().join(' ')).not.toContain('secret-payload')

    const data = { capture_id: 'c1' }
    handler({ data: JSON.stringify(data) } as MessageEvent)
    expect(onEvent).toHaveBeenCalledWith({ type: 'capture.extracted', data })
    warn.mockRestore()
  })
})
