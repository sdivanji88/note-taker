import { describe, expect, it } from 'vitest'
import { fieldsFromServer, SERVER_FIELD_TEXT } from '../src/screens/settingsForm'

// The backend names rejected fields by their dotted path in Settings; this pins how each
// maps onto a form input so a renamed field on either side fails here, not silently in the UI.
describe('fieldsFromServer', () => {
  it.each([
    ['notes_repo.remote_url', 'remote_url'],
    ['notes_repo.branch', 'branch'],
    ['notes_repo.local_path', 'local_path'],
    ['notes_repo.books_dir', 'books_dir'],
    ['extractor.ollama.base_url', 'base_url'],
    ['extractor.ollama.model', 'model'],
    ['extractor.concurrency', 'concurrency'],
    ['extractor.timeout_s', 'timeout_s'],
    ['batches.expiry_days', 'expiry_days'],
    ['batches.warn_days_before', 'warn_days_before']
  ])('%s -> %s', (path, field) => {
    expect(fieldsFromServer([path])).toEqual({ [field]: SERVER_FIELD_TEXT })
  })

  it('ignores paths that have no focusable input (the kind radios, tesseract tuning, unknown)', () => {
    expect(fieldsFromServer(['extractor.kind', 'extractor.tesseract.lang', 'nope', ''])).toEqual({})
  })

  it('keeps the mapped paths and drops the rest', () => {
    expect(Object.keys(fieldsFromServer(['extractor.kind', 'notes_repo.branch', 'batches.expiry_days'])).sort()).toEqual([
      'branch',
      'expiry_days'
    ])
  })
})
