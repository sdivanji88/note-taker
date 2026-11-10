import type { Capture } from '../api/types'

interface Props {
  capture: Capture
  src: string
  rotateDisabled: boolean
  // Rotation of a ready capture changes only the picture: re-extracting would overwrite edits.
  rotatedReady: boolean
  rerunVisible: boolean
  rerunDisabled: boolean
  onRotate: () => void
  onRerun: () => void
}

export default function CapturePhoto({
  capture, src, rotateDisabled, rotatedReady, rerunVisible, rerunDisabled, onRotate, onRerun
}: Props) {
  if (capture.source === 'kindle' || !capture.image_file) {
    return (
      <div className="review-photo kindle-panel">
        <strong>Kindle highlight</strong>
        <p className="muted">Pasted from Kindle; there is no photo.</p>
      </div>
    )
  }
  const alt = `Photo of ${capture.book_slug ?? 'book'} page ${capture.page ?? 'unknown'}`
  return (
    <div className="review-photo">
      <div className="row">
        <button type="button" disabled={rotateDisabled} onClick={onRotate}>Rotate ↻</button>
        {rerunVisible && (
          <button type="button" disabled={rerunDisabled} onClick={onRerun}>Re-run extraction</button>
        )}
      </div>
      {rotatedReady && (
        <p className="muted">Rotation changes the photo view only; highlights already extracted are unchanged.</p>
      )}
      <img src={src} alt={alt} />
    </div>
  )
}
