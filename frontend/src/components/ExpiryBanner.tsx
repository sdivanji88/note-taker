import type { BatchSummary } from '../api/types'
import { formatDate } from '../format'

// The date is the soonest deadline: the user needs to know when the first deletion hits.
export default function ExpiryBanner({ batches }: { batches: BatchSummary[] }) {
  const expiring = batches.filter((b) => b.expiring_soon)
  if (expiring.length === 0) return null
  const soonest = expiring.map((b) => b.expires_at).sort()[0]
  const n = expiring.length
  return (
    <div role="alert" aria-label="Batches expiring" className="banner warn">
      {n} {n === 1 ? 'batch' : 'batches'} will be deleted soon: {formatDate(soonest)}. Resume or discard them.
    </div>
  )
}
