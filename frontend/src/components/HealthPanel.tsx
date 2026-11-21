import type { Health } from '../api/types'

interface Props {
  health: Health | null
  error: string | null
  onRecheck: () => void
}

// Status is spelled out ("OK"/"Not OK") so it never relies on colour alone. All detail
// strings come from the backend and are rendered as React text only.
export default function HealthPanel({ health, error, onRecheck }: Props) {
  const status = (ok: boolean) => <strong className={ok ? 'status-ok' : 'status-bad'}>{ok ? 'OK' : 'Not OK'}</strong>
  return (
    <section aria-labelledby="health-title">
      <div className="row between">
        <h2 id="health-title">Health</h2>
        <button type="button" onClick={onRecheck}>Re-check</button>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {health && (
        <ul className="health">
          <li>
            Extractor ({health.extractor.kind}): {status(health.extractor.ok)}{' '}
            <span className="detail">{health.extractor.detail}</span>
          </li>
          <li>
            Repo: {health.repo.cloned ? 'cloned' : 'not cloned'}; uncommitted changes:{' '}
            {health.repo.dirty === null ? 'unknown' : health.repo.dirty ? 'yes' : 'no'};{' '}
            <span className="detail">{health.repo.path}</span>
          </li>
          <li>
            Remote: {status(health.remote.ok)} <span className="detail">{health.remote.detail}</span>
          </li>
        </ul>
      )}
    </section>
  )
}
