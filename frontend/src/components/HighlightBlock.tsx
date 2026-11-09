import type { HighlightDraft } from '../review/draft'

interface Props {
  highlight: HighlightDraft
  disabled: boolean
  autoFocus: boolean
  onChange: (patch: Partial<Pick<HighlightDraft, 'text' | 'note'>>) => void
  onRemove: () => void
}

export default function HighlightBlock({ highlight, disabled, autoFocus, onChange, onRemove }: Props) {
  return (
    <div className="highlight-block" data-testid="highlight-block">
      <label>
        Highlight text
        <textarea
          rows={4}
          value={highlight.text}
          disabled={disabled}
          autoFocus={autoFocus}
          onChange={(e) => onChange({ text: e.target.value })}
        />
      </label>
      <label>
        My note
        <textarea rows={2} value={highlight.note} disabled={disabled} onChange={(e) => onChange({ note: e.target.value })} />
      </label>
      <button type="button" className="danger" disabled={disabled} onClick={onRemove}>
        Remove highlight
      </button>
    </div>
  )
}
