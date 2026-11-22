// Backend timestamps are ISO-8601 with an offset; anything else is shown verbatim rather
// than risk a locale-dependent Date parse producing a wrong day.
const ISO = /^\d{4}-\d{2}-\d{2}T/

export function formatDate(s: string): string {
  if (!ISO.test(s)) return s
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString()
}

const DAY_MS = 86_400_000

// Short "when does this go away" label for the per-batch pill. Whole days are rounded down
// so the label never promises more time than the batch has; an unreadable date still says
// something true rather than guessing.
export function expiryPillText(expiresAt: string, now: number = Date.now()): string {
  const left = new Date(expiresAt).getTime() - now
  if (Number.isNaN(left)) return 'Expires soon'
  if (left <= 0) return 'Expired — will be deleted soon'
  if (left < DAY_MS) return 'Expires today'
  const days = Math.floor(left / DAY_MS)
  return `Expires in ${days} ${days === 1 ? 'day' : 'days'}`
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// ApiError carries status 0 / code network_error when the backend is unreachable; its raw
// message is a fetch internal that means nothing to the user.
export function friendlyError(e: unknown): string {
  if (e instanceof Error && (e as { code?: string }).code === 'network_error') return "Can't reach the backend."
  return errorMessage(e)
}
