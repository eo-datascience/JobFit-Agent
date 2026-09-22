import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Profile, Snapshot } from './types'

type State =
  | { status: 'loading' }
  | { status: 'ready'; data: Snapshot }
  | { status: 'missing' }
  | { status: 'error'; message: string }

async function load(name: string): Promise<Snapshot | null> {
  const res = await fetch(`${import.meta.env.BASE_URL}data/${name}`, { cache: 'no-cache' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`The snapshot returned ${res.status}.`)
  // A dev server answers unknown paths with index.html, so a missing file can
  // arrive as HTML with status 200. Only JSON counts as a snapshot.
  if (!(res.headers.get('content-type') ?? '').includes('json')) return null
  return (await res.json()) as Snapshot
}

const SnapshotContext = createContext<State>({ status: 'loading' })

export function SnapshotProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        let data = await load('dashboard.json')
        // Sample data is only ever read in development, and only when no real
        // snapshot exists, so it can never reach the published site.
        if (!data && import.meta.env.DEV) data = await load('sample.json')
        if (!cancelled) setState(data ? { status: 'ready', data } : { status: 'missing' })
      } catch (err) {
        if (!cancelled) setState({ status: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })()
    return () => { cancelled = true }
  }, [])

  return <SnapshotContext.Provider value={state}>{children}</SnapshotContext.Provider>
}

export function useSnapshotState(): State {
  return useContext(SnapshotContext)
}

export function useSnapshot(): Snapshot {
  const state = useContext(SnapshotContext)
  if (state.status !== 'ready') throw new Error('useSnapshot called before the snapshot loaded')
  return state.data
}

// ------------------------------------------------------------------ profile

const STORAGE_KEY = 'jobfit.profile'

interface ProfileState {
  profileId: string | null
  setProfileId: (id: string) => void
}

const ProfileContext = createContext<ProfileState>({ profileId: null, setProfileId: () => {} })

function remembered(): string | null {
  try { return localStorage.getItem(STORAGE_KEY) } catch { return null }
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profileId, setId] = useState<string | null>(remembered)
  const setProfileId = useCallback((id: string) => {
    setId(id)
    try { localStorage.setItem(STORAGE_KEY, id) } catch { /* storage unavailable */ }
  }, [])
  return <ProfileContext.Provider value={{ profileId, setProfileId }}>{children}</ProfileContext.Provider>
}

/** The profile currently being scored against, falling back to the first. */
export function useProfile(): { profile: Profile; setProfileId: (id: string) => void } {
  const s = useSnapshot()
  const { profileId, setProfileId } = useContext(ProfileContext)
  const profile = s.profiles.find((p) => p.id === profileId) ?? s.profiles[0]
  return { profile, setProfileId }
}

export function useProfileControl() {
  return useContext(ProfileContext)
}
