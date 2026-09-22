import { AGENTS, BUGS, PRINCIPLES } from '../content/howItWorks'

const REPO = 'https://github.com/eo-datascience/JobFit-Agent'

export default function HowItWorks() {
  return (
    <>
      <header className="page-head">
        <h1>How it works</h1>
        <p className="lead">
          Six agents run in sequence every Monday, each handing its output to the next. The
          design choices below were mostly forced by real data: almost every one exists because
          an earlier version gave a confident wrong answer.
        </p>
      </header>

      <section aria-labelledby="agents">
        <h2 id="agents" style={{ marginBottom: '1.25rem' }}>The six agents</h2>
        <ol className="agents">
          {AGENTS.map((a, i) => (
            <li className="agent" key={a.name}>
              <span className="agent-n" aria-hidden="true">{i + 1}</span>
              <h3>{a.name}</h3>
              <p>{a.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="section" aria-labelledby="arch">
        <h2 id="arch">Where it runs</h2>
        <p className="intro">
          There is no server. A scheduled job does the work and then stops, and personal data
          is kept in a separate private repository so that it never sits beside public code.
        </p>
        <div className="arch">
          <div className="arch-cell">
            <h3>Public repository</h3>
            <p>The code and over 250 tests. Everything in it is safe to publish.</p>
          </div>
          <div className="arch-cell">
            <h3>GitHub Actions</h3>
            <p>Runs every Monday at 07:00. Fetches postings once, scores them, sends the email and rebuilds this site.</p>
          </div>
          <div className="arch-cell private">
            <span className="arch-tag">Private</span>
            <h3>State repository</h3>
            <p>The candidate's CV, the roles already sent and application outcomes. Read and written by the weekly job alone.</p>
          </div>
          <div className="arch-cell">
            <h3>This site</h3>
            <p>Static, rebuilt each week from a snapshot of the run. Scored against a sample profile, never a real CV.</p>
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="principles">
        <h2 id="principles" style={{ marginBottom: '1.5rem' }}>Principles that came out of it</h2>
        <div className="principles">
          {PRINCIPLES.map((p) => (
            <div className="principle" key={p.title}>
              <h3>{p.title}</h3>
              <p>{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section" id="log" aria-labelledby="log-title">
        <h2 id="log-title">Twelve bugs found by running it for real</h2>
        <p className="intro">
          None of these showed up in the test suite. Each one appeared only once the system met
          real postings, and each now has a test so it cannot quietly return. They are listed in
          the order they were found.
        </p>
        <ol className="log" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {BUGS.map((b, i) => (
            <li className="entry" key={b.title}>
              <span className="entry-n" aria-hidden="true">{i + 1}</span>
              <div>
                <h3>{b.title}</h3>
                <span className="agent-of">{b.agent} agent</span>
                <dl>
                  <div><dt>What happened</dt><dd>{b.what}</dd></div>
                  <div><dt>Why</dt><dd>{b.why}</dd></div>
                  <div><dt>The fix</dt><dd>{b.fix}</dd></div>
                </dl>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <p className="muted" style={{ marginTop: '3rem' }}>
        The full source, tests and deployment workflow are <a href={REPO}>on GitHub</a>.
      </p>
    </>
  )
}
