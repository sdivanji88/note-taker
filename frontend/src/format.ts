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
