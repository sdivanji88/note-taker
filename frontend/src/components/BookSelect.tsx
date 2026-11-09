import { useCallback, useEffect, useId, useState } from 'react'
import { useApi } from '../api/context'
import type { Book, BookKind } from '../api/types'
import { errorMessage } from '../format'

interface Props {
  value: string | null
  onChange: (slug: string | null) => void
  allowCreate?: boolean
  disabled?: boolean
  label?: string
  // Text of the empty option; the review editor uses it to show the batch default.
  noneLabel?: string
}

const NEW = '__new__'

export default function BookSelect({ value, onChange, allowCreate = false, disabled = false, label = 'Book', noneLabel = '(none)' }: Props) {
  const api = useApi()
  const id = useId()
  const [books, setBooks] = useState<Book[]>([])
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [kind, setKind] = useState<BookKind>('non-fiction')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setBooks(await api.listBooks())
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [api])
  useEffect(() => {
    void load()
  }, [load])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    try {
      const created = await api.createBook({ title: title.trim(), author: author.trim() || null, kind })
      await load()
      setCreating(false)
      setTitle('')
      setAuthor('')
      setError(null)
      onChange(created.slug)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="book-select">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => (e.target.value === NEW ? setCreating(true) : onChange(e.target.value || null))}
      >
        <option value="">{noneLabel}</option>
        {books.map((b) => (
          <option key={b.slug} value={b.slug}>
            {b.title}
            {b.pending ? ' (new)' : ''}
          </option>
        ))}
        {allowCreate && <option value={NEW}>+ New book…</option>}
      </select>
      {creating && (
        <form onSubmit={create} className="new-book" aria-label="New book">
          <label>
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label>
            Author
            <input value={author} onChange={(e) => setAuthor(e.target.value)} />
          </label>
          <label>
            Kind
            <select value={kind} onChange={(e) => setKind(e.target.value as BookKind)}>
              <option value="non-fiction">non-fiction</option>
              <option value="fiction">fiction</option>
            </select>
          </label>
          <button type="submit">Create book</button>
          <button type="button" onClick={() => setCreating(false)}>Cancel</button>
        </form>
      )}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  )
}
