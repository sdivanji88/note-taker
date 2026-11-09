import type { CaptureStatus, ExtractorKind } from '../api/types'

interface Props {
  position: number
  total: number
  status: CaptureStatus
  busy: boolean
  readOnly: boolean
  canDiscard: boolean
  extractor: ExtractorKind
  onPrev: () => void
  onNext: () => void
  onDiscard: () => void
  onApprove: () => void
  onUnapprove: () => void
  onExtractor: (k: ExtractorKind) => void
  onRetry: () => void
}

export default function ReviewFooter(p: Props) {
  return (
    <footer className="review-footer row between">
      <div className="row">
        <button type="button" aria-label="Previous" disabled={p.busy || p.position <= 1} onClick={p.onPrev}>◀</button>
        <span>{`${p.position} of ${p.total}`}</span>
        <button type="button" aria-label="Next" disabled={p.busy || p.position >= p.total} onClick={p.onNext}>▶</button>
      </div>
      <div className="row">
        {p.status === 'failed' && (
          <>
            <label>
              <span className="sr-only">Extractor</span>
              <select aria-label="Extractor" value={p.extractor} disabled={p.busy || p.readOnly}
                onChange={(e) => p.onExtractor(e.target.value as ExtractorKind)}>
                <option value="tesseract">tesseract</option>
                <option value="ollama">ollama</option>
              </select>
            </label>
            <button type="button" disabled={p.busy || p.readOnly} onClick={p.onRetry}>Retry</button>
          </>
        )}
        <button type="button" className="danger" disabled={p.busy || !p.canDiscard} onClick={p.onDiscard}>Discard</button>
        {p.status === 'approved' ? (
          <button type="button" disabled={p.busy || p.readOnly} onClick={p.onUnapprove}>Unapprove</button>
        ) : (
          <button type="button" disabled={p.busy || p.readOnly} onClick={p.onApprove}>Approve</button>
        )}
      </div>
    </footer>
  )
}
