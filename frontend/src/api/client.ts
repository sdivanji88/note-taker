import {
  ApiError,
  type BackendConfig,
  type Batch,
  type BatchEvent,
  type BatchSummary,
  type Book,
  type Capture,
  type CapturePatch,
  type ExtractorKind,
  type Health,
  type KindleInput,
  type NewBook,
  type PushResult,
  type RepoHealth,
  type Settings,
  type UploadResult
} from './types'

// Every SSE `event:` name the backend emits; EventSource only delivers named events
// to listeners registered for that exact name.
const EVENT_TYPES: BatchEvent['type'][] = [
  'capture.status_changed',
  'capture.extracted',
  'batch.push_progress'
]

export type ApiClient = ReturnType<typeof createClient>

export function createClient(cfg: BackendConfig) {
  const { baseUrl, token } = cfg

  async function parseError(res: Response): Promise<ApiError> {
    let code = 'http_error'
    let message = res.statusText || `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body?.error?.code === 'string') code = body.error.code
      if (typeof body?.error?.message === 'string') message = body.error.message
    } catch {
      // Not the standard error body (proxy page, empty reply): keep the fallback.
    }
    // The backend redacts its own messages; this is a second line of defence.
    return new ApiError(res.status, code, message.split(token).join('[redacted]'))
  }

  async function request<T>(
    method: string,
    path: string,
    opts: { json?: unknown; form?: FormData } = {}
  ): Promise<T> {
    const headers = new Headers({ 'X-Session-Token': token })
    let body: BodyInit | undefined
    if (opts.form) {
      body = opts.form // no Content-Type: fetch must add the multipart boundary
    } else if (opts.json !== undefined) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(opts.json)
    }

    let res: Response
    try {
      res = await fetch(`${baseUrl}${path}`, { method, headers, body })
    } catch {
      // The underlying message can echo the request URL; keep ours fixed.
      throw new ApiError(0, 'network_error', 'could not reach the Note Taker backend')
    }
    if (!res.ok) throw await parseError(res)
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  }

  // <img> and EventSource cannot send headers, so these two (and only these two)
  // put the token in the query string, which the backend accepts only on those routes.
  const withToken = (path: string) => `${baseUrl}${path}?token=${encodeURIComponent(token)}`
  const enc = encodeURIComponent

  return {
    getHealth: () => request<Health>('GET', '/health'),
    getSettings: () => request<Settings>('GET', '/settings'),
    putSettings: (s: Settings) => request<Settings>('PUT', '/settings', { json: s }),
    connectRepo: () => request<RepoHealth>('POST', '/repo/connect'),

    listBooks: () => request<Book[]>('GET', '/books'),
    createBook: (b: NewBook) => request<Book>('POST', '/books', { json: b }),

    listBatches: () => request<BatchSummary[]>('GET', '/batches'),
    createBatch: (defaultBookSlug: string | null = null) =>
      request<Batch>('POST', '/batches', { json: { default_book_slug: defaultBookSlug } }),
    getBatch: (batchId: string) => request<Batch>('GET', `/batches/${enc(batchId)}`),
    patchBatch: (batchId: string, body: { default_book_slug: string | null }) =>
      request<Batch>('PATCH', `/batches/${enc(batchId)}`, { json: body }),
    deleteBatch: (batchId: string) => request<void>('DELETE', `/batches/${enc(batchId)}`),

    uploadPhotos: (batchId: string, files: File[]) => {
      const form = new FormData()
      for (const f of files) form.append('files', f, f.name)
      return request<UploadResult>('POST', `/batches/${enc(batchId)}/captures`, { form })
    },
    addKindle: (batchId: string, body: KindleInput) =>
      request<Capture>('POST', `/batches/${enc(batchId)}/captures`, { json: body }),

    patchCapture: (captureId: string, body: CapturePatch) =>
      request<Capture>('PATCH', `/captures/${enc(captureId)}`, { json: body }),
    retryCapture: (captureId: string, extractor?: ExtractorKind) =>
      request<Capture>('POST', `/captures/${enc(captureId)}/retry`, {
        json: extractor ? { extractor } : {}
      }),
    deleteCapture: (captureId: string) => request<void>('DELETE', `/captures/${enc(captureId)}`),

    imageUrl: (captureId: string) => withToken(`/captures/${enc(captureId)}/image`),

    subscribe: (batchId: string, onEvent: (e: BatchEvent) => void): (() => void) => {
      const es = new EventSource(withToken(`/batches/${enc(batchId)}/events`))
      for (const type of EVENT_TYPES) {
        es.addEventListener(type, (e) => {
          onEvent({ type, data: JSON.parse((e as MessageEvent).data) } as BatchEvent)
        })
      }
      return () => es.close()
    },

    push: (batchId: string) => request<PushResult>('POST', `/batches/${enc(batchId)}/push`)
  }
}
