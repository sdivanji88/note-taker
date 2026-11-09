import { useEffect, useRef } from 'react'

interface Props {
  title: string
  message: string
  confirmLabel: string
  cancelLabel?: string
  onConfirm: () => void
  onCancel: () => void
}

// Rendered in-page rather than via window.confirm so it is testable and looks the same in
// Electron. Focus starts on Cancel: the actions that use this are destructive, and a
// stray Enter should not be the thing that deletes.
export default function ConfirmDialog({ title, message, confirmLabel, cancelLabel = 'Cancel', onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    cancelRef.current?.focus()
    return () => previous?.focus?.()
  }, [])

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onCancel()
    } else if (e.key === 'Tab') {
      // Two buttons only: keep Tab cycling between them.
      const first = cancelRef.current
      const last = confirmRef.current
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last?.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first?.focus()
      }
    }
  }

  return (
    <div className="overlay">
      <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="dialog" onKeyDown={onKeyDown}>
        <h2 id="confirm-title">{title}</h2>
        <p>{message}</p>
        <div className="row">
          <button ref={cancelRef} onClick={onCancel}>{cancelLabel}</button>
          <button ref={confirmRef} className="danger" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}
