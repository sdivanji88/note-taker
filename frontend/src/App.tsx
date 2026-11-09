import { useState } from 'react'
import BatchGrid from './screens/BatchGrid'
import BatchList from './screens/BatchList'

export type Route =
  | { screen: 'list' }
  | { screen: 'grid'; batchId: string }
  | { screen: 'review'; batchId: string; index: number }
  | { screen: 'settings' }

// Tasks 14 and 15 replace these.
function Placeholder({ text, onBack }: { text: string; onBack: () => void }) {
  return (
    <main className="screen">
      <button onClick={onBack}>← Back</button>
      <p>{text}</p>
    </main>
  )
}

export default function App() {
  const [route, setRoute] = useState<Route>({ screen: 'list' })
  const toList = () => setRoute({ screen: 'list' })

  switch (route.screen) {
    case 'list':
      return (
        <BatchList
          onOpenBatch={(batchId) => setRoute({ screen: 'grid', batchId })}
          onSettings={() => setRoute({ screen: 'settings' })}
        />
      )
    case 'grid':
      return (
        <BatchGrid
          batchId={route.batchId}
          onOpenReview={(index) => setRoute({ screen: 'review', batchId: route.batchId, index })}
          onBack={toList}
        />
      )
    case 'review':
      return (
        <Placeholder
          text="Review screen — Task 14"
          onBack={() => setRoute({ screen: 'grid', batchId: route.batchId })}
        />
      )
    case 'settings':
      return <Placeholder text="Settings screen — Task 15" onBack={toList} />
  }
}
