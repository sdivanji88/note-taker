import { useState } from 'react'
import BatchGrid from './screens/BatchGrid'
import BatchList from './screens/BatchList'
import ReviewEditor from './screens/ReviewEditor'
import Settings from './screens/Settings'

export type Route =
  | { screen: 'list' }
  | { screen: 'grid'; batchId: string }
  | { screen: 'review'; batchId: string; index: number }
  | { screen: 'settings' }

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
        <ReviewEditor
          batchId={route.batchId}
          index={route.index}
          onBack={() => setRoute({ screen: 'grid', batchId: route.batchId })}
        />
      )
    case 'settings':
      return <Settings onBack={toList} />
  }
}
