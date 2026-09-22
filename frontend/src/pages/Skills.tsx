import { Link } from 'react-router-dom'
import { useProfile, useSnapshot } from '../data'
import { num } from '../format'

const SHOWN = 25

export default function Skills() {
  const s = useSnapshot()
  const { profile } = useProfile()
  const has = new Set(profile.skills)
  const demand = s.skills.demand
  const rows = demand.slice(0, SHOWN)
  const widest = Math.max(...rows.map((r) => r.share), 1)
  const described = s.skills.described

  const ranked = demand.filter((k) => k.essential_share !== null)
  const mostMandatory = [...ranked].sort((a, b) => (b.essential_share ?? 0) - (a.essential_share ?? 0))[0]
  const leastMandatory = [...ranked].sort((a, b) => (a.essential_share ?? 0) - (b.essential_share ?? 0))[0]

  const { weeks_recorded: recorded, weeks_needed: needed } = s.skills
  const rising = s.skills.trends.filter((t) => t.trend === 'rising')
  const falling = s.skills.trends.filter((t) => t.trend === 'falling')

  return (
    <>
      <header className="page-head">
        <h1>What the market is asking for</h1>
        <p className="lead">
          Every skill below was matched word for word in the {num(described)} data postings this
          week that came with a full description. Excerpts are left out, because one that never
          names a skill is not evidence the role does not want it. How often a skill appears is
          one question. How often it is stated as essential when it does appear is another, and
          often more useful.
        </p>
      </header>

      {mostMandatory && leastMandatory && mostMandatory.skill !== leastMandatory.skill && (
        <div className="facts" style={{ marginBottom: '3rem' }}>
          <div className="fact">
            <strong>{demand[0]?.skill}</strong>
            <span>asked for most, in {demand[0]?.share}% of postings</span>
          </div>
          <div className="fact">
            <strong>{mostMandatory.skill}</strong>
            <span>most often essential, in {mostMandatory.essential_share}% of the postings that mention it</span>
          </div>
          <div className="fact">
            <strong>{leastMandatory.skill}</strong>
            <span>least often essential, in {leastMandatory.essential_share}% of the postings that mention it</span>
          </div>
        </div>
      )}

      <section aria-labelledby="demand">
        <h2 id="demand" style={{ marginBottom: '1.25rem' }}>The {rows.length} most asked for skills</h2>
        <table className="skill-table">
          <thead>
            <tr>
              <th scope="col">Skill</th>
              <th scope="col" className="bar-cell"><span className="sr-only">Share of postings</span></th>
              <th scope="col" className="num">Postings</th>
              <th scope="col" className="num">Share</th>
              <th scope="col" className="num">Essential when asked</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((k) => (
              <tr key={k.skill}>
                <td><span className={`skill-name${has.has(k.skill) ? ' have' : ''}`}>{k.skill}</span></td>
                <td className="bar-cell">
                  <div className="share-track">
                    <div className="share-fill" style={{ width: `${(k.share / widest) * 100}%` }} />
                  </div>
                </td>
                <td className="num">{num(k.postings)}</td>
                <td className="num">{k.share}%</td>
                <td className="num">
                  {k.essential_share === null
                    ? <span className="na" title="Too few fully described postings to give a reliable rate">too few</span>
                    : `${k.essential_share}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small" style={{ marginTop: '1rem', maxWidth: '68ch' }}>
          Skills in green are ones the selected profile has. Essential rates are withheld below five
          postings, because at that size one posting would swing them too far.
        </p>
      </section>

      {s.skills.pairs.length > 0 && (
        <section className="section" aria-labelledby="together">
          <h2 id="together">Asked for together</h2>
          <p className="intro">
            The pairs of skills that most often appear in the same posting, which says more about
            what a role actually involves than either skill does on its own.
          </p>
          <div className="pairs">
            {s.skills.pairs.slice(0, 10).map((p) => (
              <div className="pair" key={`${p.a}-${p.b}`}>
                <span><strong>{p.a}</strong> with <strong>{p.b}</strong></span>
                <span className="muted">{num(p.postings)} postings</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="section" aria-labelledby="trends">
        <h2 id="trends">Trends over time</h2>
        {recorded >= needed ? (
          <div className="two-col">
            <div>
              <h3 style={{ marginBottom: '0.75rem' }}>Rising</h3>
              {rising.length ? rising.map((t) => (
                <div className="pair" key={t.skill}><strong>{t.skill}</strong>
                  <span className="muted">{t.change_pct !== null ? `+${Math.round(t.change_pct)}%` : 'emerging'}</span></div>
              )) : <p className="muted">Nothing is clearly rising.</p>}
            </div>
            <div>
              <h3 style={{ marginBottom: '0.75rem' }}>Falling</h3>
              {falling.length ? falling.map((t) => (
                <div className="pair" key={t.skill}><strong>{t.skill}</strong>
                  <span className="muted">{t.change_pct !== null ? `${Math.round(t.change_pct)}%` : ''}</span></div>
              )) : <p className="muted">Nothing is clearly falling.</p>}
            </div>
          </div>
        ) : (
          <>
            <p className="intro">
              Trends appear once the system has recorded {needed} weeks of its own history. It could
              reconstruct history from the dates postings were published instead, and it tried. That
              produced four different wrong answers, each for a different reason, so it now waits for
              real data rather than showing a confident guess.{' '}
              <Link to="/how-it-works#log">Read what went wrong</Link>.
            </p>
            <div className="progress">
              <div className="progress-steps" style={{ ['--n' as string]: needed }}>
                {Array.from({ length: needed }, (_, i) => (
                  <div key={i} className={i < recorded ? 'done' : ''} />
                ))}
              </div>
              <p>{recorded} of {needed} weeks recorded.</p>
            </div>
          </>
        )}
      </section>
    </>
  )
}
