import { useState } from 'react'

// Recording an outcome from the site.
//
// The browser never holds anything that can write to the private state
// repository. It posts to a Netlify function, which holds the token and
// triggers the same workflow the Actions tab uses, so there is one code path
// whichever way an outcome is recorded.
//
// The passphrase is a shared secret, kept in this browser once entered. It is
// not an account system. It guards an endpoint whose worst case is a stranger
// adding a made up job outcome, and it is the strongest thing available without
// running a login service for a single user.

const OUTCOMES = ['applied', 'response', 'interview', 'offer', 'rejected'] as const
type OutcomeName = (typeof OUTCOMES)[number]

const STORAGE_KEY = 'jobfit.record-secret'

const remembered = () => {
  try { return localStorage.getItem(STORAGE_KEY) ?? '' } catch { return '' }
}

export default function RecordOutcome({ outcomeKey }: { outcomeKey: string }) {
  const [secret, setSecret] = useState(remembered)
  const [busy, setBusy] = useState<OutcomeName | null>(null)
  const [done, setDone] = useState<OutcomeName | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function send(outcome: OutcomeName) {
    setBusy(outcome)
    setError(null)
    try {
      const res = await fetch('/api/record-outcome', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ key: outcomeKey, outcome, secret }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error ?? `That failed with status ${res.status}.`)
      }
      try { localStorage.setItem(STORAGE_KEY, secret) } catch { /* storage unavailable */ }
      setDone(outcome)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That could not be sent.')
    } finally {
      setBusy(null)
    }
  }

  if (done) {
    return (
      <div className="record" role="status">
        <p><strong>Recorded as {done}.</strong> The run takes a moment, and the outcome
        monitor picks it up from there.</p>
      </div>
    )
  }

  return (
    <div className="record">
      <h3>Record what happened</h3>
      <p className="muted small">
        For the owner of this system. Outcomes teach the scoring which factors actually predicted
        a reply, and nothing is adjusted until there are twenty of them.
      </p>
      <div className="field" style={{ marginTop: '0.9rem', maxWidth: '22rem' }}>
        <label htmlFor="secret">Passphrase</label>
        <input
          id="secret"
          type="password"
          value={secret}
          autoComplete="current-password"
          onChange={(e) => setSecret(e.target.value)}
        />
      </div>
      <div className="record-buttons">
        {OUTCOMES.map((outcome) => (
          <button
            key={outcome}
            type="button"
            className="record-button"
            disabled={!secret || busy !== null}
            onClick={() => send(outcome)}
          >
            {busy === outcome ? 'Sending' : outcome}
          </button>
        ))}
      </div>
      {error && <p className="notice" style={{ marginTop: '0.9rem' }}>{error}</p>}
    </div>
  )
}
