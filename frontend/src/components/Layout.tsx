import { NavLink, Outlet, Link, useLocation } from 'react-router-dom'
import { useSnapshotState } from '../data'
import { longDate } from '../format'
import ProfileSwitch from './ProfileSwitch'

const REPO = 'https://github.com/eo-datascience/JobFit-Agent'

function Mark() {
  // Three narrowing bars: the pipeline, reduced to a glyph.
  return (
    <svg width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
      <rect x="0" y="0" width="18" height="3.4" rx="1" fill="currentColor" />
      <rect x="0" y="6.3" width="11" height="3.4" rx="1" fill="currentColor" />
      <rect x="0" y="12.6" width="5" height="3.4" rx="1" fill="var(--jade)" />
    </svg>
  )
}

export default function Layout() {
  const state = useSnapshotState()
  const { pathname } = useLocation()
  const snapshot = state.status === 'ready' ? state.data : null

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      {snapshot?.is_sample && (
        <div className="sample-banner" role="note">
          <div className="frame">
            Sample data for development. This is not a live run, and every employer named here is fictional.
          </div>
        </div>
      )}
      <header className="masthead">
        <div className="frame">
          <Link to="/" className="wordmark"><Mark />JobFit <span>Agent</span></Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>This week</NavLink>
            <NavLink to="/roles">Roles</NavLink>
            <NavLink to="/skills">Skills</NavLink>
            <NavLink to="/how-it-works">How it works</NavLink>
          </nav>
        </div>
      </header>
      {/* Hidden where no score is shown, so the control never looks inert. */}
      {snapshot && snapshot.profiles.length > 1 && pathname !== '/how-it-works' && <ProfileSwitch />}

      <main id="main">
        <div className="frame">
          <Outlet />
        </div>
      </main>

      <footer className="footer">
        <div className="frame">
          <p>
            Postings come from Reed.co.uk and Adzuna, and each links back to its original listing.
            Scores are calculated against public sample profiles, never a real person.
            {snapshot && <> Last updated {longDate(snapshot.generated_at)}.</>}
          </p>
          <p><a href={REPO}>Source on GitHub</a></p>
        </div>
      </footer>
    </>
  )
}
