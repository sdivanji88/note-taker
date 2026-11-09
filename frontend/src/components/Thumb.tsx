import type { Capture, CaptureStatus } from '../api/types'

const BADGE: Record<CaptureStatus, string> = {
  pending: '…',
  extracting: '⟳',
  ready: '✓',
  failed: '✗',
  approved: '✓✓',
  pushed: '',
  discarded: '–'
}

// The ones the backend lets a user edit; pending/extracting would get 409 invalid_transition.
export const REVIEWABLE: CaptureStatus[] = ['ready', 'failed', 'approved']

interface Props {
  capture: Capture
  imageUrl: string | null
  position: number
  selected: boolean
  disabled: boolean
  onToggle: () => void
  onOpen: () => void
}

export default function Thumb({ capture, imageUrl, position, selected, disabled, onToggle, onOpen }: Props) {
  const reviewable = REVIEWABLE.includes(capture.status)
  const label = [
    capture.source === 'kindle' ? 'Kindle highlight' : 'Photo',
    String(position),
    capture.page != null ? `page ${capture.page}` : null,
    capture.book_slug
  ]
    .filter(Boolean)
    .join(', ')
  const firstText = capture.highlights[0]?.text

  return (
    <li
      data-testid={`thumb-${capture.id}`}
      className={`thumb${capture.status === 'discarded' ? ' faded' : ''}${selected ? ' selected' : ''}`}
    >
      <input type="checkbox" aria-label={`Select ${label}`} checked={selected} disabled={disabled} onChange={onToggle} />
      <button
        className="thumb-open"
        aria-label={`Open ${label}`}
        disabled={!reviewable}
        title={reviewable ? undefined : 'Still extracting…'}
        onClick={onOpen}
      >
        {imageUrl ? (
          <img src={imageUrl} alt={label} loading="lazy" />
        ) : (
          <span className="kindle">{firstText || 'Kindle highlight'}</span>
        )}
      </button>
      <span
        className={`badge badge-${capture.status}`}
        title={capture.status === 'failed' && capture.error ? capture.error : undefined}
      >
        <span aria-hidden="true" className={capture.status === 'extracting' ? 'spin' : undefined}>
          {BADGE[capture.status]}
        </span>
        <span className="sr-only">{capture.status}</span>
      </span>
    </li>
  )
}
