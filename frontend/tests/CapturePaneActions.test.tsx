import { act, fireEvent, screen } from '@testing-library/react'
import { createRef, type MutableRefObject } from 'react'
import { describe, expect, it, vi } from 'vitest'
import CapturePane, { type PaneActions } from '../src/components/CapturePane'
import type { Capture } from '../src/api/types'
import { capture, fakeClient, renderWith } from './helpers'
import { hl } from './reviewSetup'

// The id to delete and the "is it blank?" answer must come from the same pane, so the
// pane hands out the id itself rather than the parent pairing it with its own view.
function mount(c: Capture) {
  const actionsRef = createRef<PaneActions | null>() as MutableRefObject<PaneActions | null>
  actionsRef.current = null
  renderWith(
    fakeClient().client,
    <CapturePane
      capture={c}
      position={1}
      total={1}
      batchDefaultSlug={null}
      batchPushing={false}
      extractorName={null}
      loads={1}
      focusFirst={false}
      actionsRef={actionsRef}
      onSaved={vi.fn()}
      onRefresh={vi.fn(async () => {})}
      onPrev={vi.fn()}
      onNext={vi.fn()}
      onApproved={vi.fn()}
      onDiscarded={vi.fn()}
    />
  )
  return actionsRef
}

const kindle = (extra: Partial<Capture> = {}) =>
  capture('k1', 'ready', { source: 'kindle', image_file: null, highlights: [hl('h1', '')], ...extra })

describe('PaneActions.blankKindleId', () => {
  it('is the pane’s own capture id when it is an unfilled Kindle entry', () => {
    expect(mount(kindle()).current!.blankKindleId()).toBe('k1')
  })

  it('is null once anything has been typed', () => {
    const actions = mount(kindle())
    fireEvent.change(screen.getByLabelText('Chapter'), { target: { value: 'Three' } })
    act(() => {})
    expect(actions.current!.blankKindleId()).toBeNull()
  })

  it('is null for a Kindle entry that already has text', () => {
    expect(mount(kindle({ highlights: [hl('h1', 'quote')] })).current!.blankKindleId()).toBeNull()
  })

  it('is null for a photo capture, which is never blank', () => {
    expect(mount(capture('p1', 'ready', { highlights: [] })).current!.blankKindleId()).toBeNull()
  })
})
