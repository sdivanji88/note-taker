// Backend timestamps are ISO-8601 with an offset; anything else is shown verbatim rather
// than risk a locale-dependent Date parse producing a wrong day.
const ISO = /^\d{4}-\d{2}-\d{2}T/

export function formatDate(s: string): string {
  if (!ISO.test(s)) return s
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString()
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
