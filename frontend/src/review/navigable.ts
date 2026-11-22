import type { Capture } from '../api/types'

// The one definition of "a capture the user can step through": pushed ones are gone from
// the UI and discarded ones are only shown faded. The grid's "Review k of N" and numbering
// and the editor's "k of N" must agree, so both count with this predicate.
// Pending/extracting captures count: they are shown (read-only) in the editor.
export const navigable = (c: Capture) => c.status !== 'pushed' && c.status !== 'discarded'
