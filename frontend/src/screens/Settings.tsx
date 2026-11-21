import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../api/context'
import { ApiError, type Health, type Settings as SettingsT } from '../api/types'
import ConfirmDialog from '../components/ConfirmDialog'
import HealthPanel from '../components/HealthPanel'
import { friendlyError } from '../format'
import { FIELD_ORDER, toForm, toSettings, urlHasCredentials, validate, type FieldName, type Form } from './settingsForm'

interface Props {
  onBack: () => void
}

const CRED_NOTICE =
  "This URL contains credentials. The app doesn't need them — use an SSH URL or your git credential helper so no token is stored in settings.json."
const RESTART = 'Changes take effect after restarting the app.'

export default function Settings({ onBack }: Props) {
  const api = useApi()
  const [server, setServer] = useState<SettingsT | null>(null)
  const [baseline, setBaseline] = useState<Form | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [connected, setConnected] = useState(false)
  const [connectError, setConnectError] = useState<{ detail: string; code: string | null } | null>(null)
  const [confirmLeave, setConfirmLeave] = useState(false)
  const inputs = useRef<Partial<Record<FieldName, HTMLInputElement | null>>>({})

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await api.getHealth())
      setHealthError(null)
    } catch (e) {
      setHealthError(`Health check failed: ${friendlyError(e)}`)
    }
  }, [api])

  const adopt = useCallback((s: SettingsT) => {
    setServer(s)
    setBaseline(toForm(s))
    setForm(toForm(s))
  }, [])

  useEffect(() => {
    api.getSettings().then(adopt, (e) => setLoadError(friendlyError(e)))
    void loadHealth()
  }, [api, adopt, loadHealth])

  if (loadError) {
    return (
      <main className="screen">
        <button onClick={onBack}>← Back</button>
        <p role="alert" className="error">{loadError}</p>
      </main>
    )
  }
  if (!form || !baseline || !server) {
    return (
      <main className="screen">
        <button onClick={onBack}>← Back</button>
        <h1>Settings</h1>
        <p>Loading…</p>
      </main>
    )
  }

  const errors = validate(form)
  const invalid = Object.keys(errors).length > 0
  const dirty = FIELD_ORDER.concat('kind').some((k) => form[k] !== baseline[k])
  // The masked URL (still unedited) carries the server's flag; an edited one is checked directly.
  const urlEdited = form.remote_url !== baseline.remote_url
  const showCredNotice = urlEdited ? urlHasCredentials(form.remote_url) : !!server.remote_url_has_credentials

  const set = (k: FieldName) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [k]: e.target.value })
    setSaved(false)
  }

  async function save(e: React.FormEvent) {
    e.preventDefault()
    if (!form || !server) return
    const first = FIELD_ORDER.find((k) => errors[k])
    if (first) {
      inputs.current[first]?.focus()
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const result = await api.putSettings(toSettings(form, server))
      adopt(result)
      setSaved(true)
      void loadHealth()
    } catch (err) {
      setSaveError(friendlyError(err))
    } finally {
      setSaving(false)
    }
  }

  async function connect() {
    setConnecting(true)
    setConnected(false)
    setConnectError(null)
    try {
      await api.connectRepo()
      setConnected(true)
      void loadHealth()
    } catch (err) {
      if (err instanceof ApiError && err.code !== 'network_error') {
        setConnectError({ detail: err.message, code: `${err.code} (HTTP ${err.status})` })
      } else {
        setConnectError({ detail: friendlyError(err), code: null })
      }
    } finally {
      setConnecting(false)
    }
  }

  function field(k: FieldName, label: string, opts: { type?: string; hint?: string } = {}) {
    const err = errors[k]
    const ids = [err && `${k}-err`, opts.hint && `${k}-hint`].filter(Boolean).join(' ') || undefined
    return (
      <div className="field">
        <label htmlFor={k}>{label}</label>
        <input
          id={k}
          ref={(el) => { inputs.current[k] = el }}
          type={opts.type ?? 'text'}
          {...(opts.type === 'number' ? { min: 0, step: 1 } : {})}
          value={form![k]}
          onChange={set(k)}
          aria-invalid={err ? true : undefined}
          aria-describedby={ids}
        />
        {err && <span id={`${k}-err`} className="error">{err}</span>}
        {opts.hint && <span id={`${k}-hint`} className="muted">{opts.hint}</span>}
      </div>
    )
  }

  const back = () => (dirty ? setConfirmLeave(true) : onBack())

  return (
    <main className="screen settings">
      <button onClick={back}>← Back</button>
      <h1>Settings</h1>
      <form aria-label="Settings" onSubmit={save} noValidate>
        <fieldset>
          <legend>Notes repo</legend>
          {field('remote_url', 'Remote URL')}
          {showCredNotice && <p className="banner warn">{CRED_NOTICE}</p>}
          {field('branch', 'Branch')}
          {field('local_path', 'Use existing clone (optional path)', {
            hint: 'The app will git pull --rebase and commit in that clone, and refuses to push when it has uncommitted changes under the books folder.'
          })}
          {field('books_dir', 'Books folder')}
          <div className="row">
            <button
              type="button"
              onClick={connect}
              disabled={connecting || dirty}
              title={dirty ? 'Save your changes first' : undefined}
            >
              Connect repo
            </button>
            {dirty && <span className="muted">Save your changes first</span>}
          </div>
          {connected && <p role="status" className="banner ok">Repo connected.</p>}
          {connectError && (
            <div role="alert" className="error">
              <pre className="stderr">{connectError.detail}</pre>
              {connectError.code && <p>Error {connectError.code}</p>}
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend>Extractor</legend>
          <fieldset className="radios">
            <legend>Extractor kind</legend>
            {(['ollama', 'tesseract'] as const).map((k) => (
              <label key={k}>
                <input
                  type="radio"
                  name="kind"
                  value={k}
                  checked={form.kind === k}
                  onChange={() => { setForm({ ...form, kind: k }); setSaved(false) }}
                />
                {k === 'ollama' ? 'Ollama (local vision)' : 'Tesseract (OCR)'}
              </label>
            ))}
          </fieldset>
          {field('base_url', 'Ollama base URL')}
          {field('model', 'Ollama model')}
          {field('concurrency', 'Concurrency', { type: 'number', hint: RESTART })}
          {field('timeout_s', 'Timeout (seconds)', { type: 'number', hint: RESTART })}
        </fieldset>

        <fieldset>
          <legend>Batches</legend>
          {field('expiry_days', 'Expiry days', { type: 'number' })}
          {field('warn_days_before', 'Warning days before expiry', { type: 'number' })}
        </fieldset>

        <div className="row">
          <button type="submit" disabled={!dirty || invalid || saving}>Save</button>
          <span aria-live="polite">{saved ? 'Saved' : ''}</span>
        </div>
        {saveError && <p role="alert" className="error">{saveError}</p>}
      </form>

      <HealthPanel health={health} error={healthError} onRecheck={loadHealth} />

      {confirmLeave && (
        <ConfirmDialog
          title="Discard unsaved settings changes?"
          message="Your edits to these settings have not been saved."
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          onConfirm={onBack}
          onCancel={() => setConfirmLeave(false)}
        />
      )}
    </main>
  )
}
