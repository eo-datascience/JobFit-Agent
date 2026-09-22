import type { ReactNode } from 'react'
import { useSnapshotState } from '../data'

// Renders children only once the snapshot is available, and says plainly what
// to do when it is not.
export default function Gate({ children }: { children: ReactNode }) {
  const state = useSnapshotState()

  if (state.status === 'loading') {
    return <p className="muted" aria-live="polite">Loading this week's run.</p>
  }
  if (state.status === 'missing') {
    return (
      <div className="empty">
        <h2>No snapshot has been published yet</h2>
        <p className="muted">
          The weekly job writes one after each run. To build one locally, run
          python run_export.py, or python tools/make_sample_snapshot.py for sample data.
        </p>
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div className="empty">
        <h2>The snapshot could not be read</h2>
        <p className="muted">{state.message} Reload the page to try again.</p>
      </div>
    )
  }
  return <>{children}</>
}
