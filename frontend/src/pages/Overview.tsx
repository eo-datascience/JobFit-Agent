import { Link } from 'react-router-dom'
import { useProfile, useSnapshot } from '../data'
import { capitalise, longDate, money, num } from '../format'

const SENIORITY_ORDER = ['junior', 'mid', 'senior', 'lead', 'not stated']

export default function Overview() {
  const s = useSnapshot()
  const { profile } = useProfile()
  const p = s.pipeline

  const funnel = [
    { key: 'fetched', count: p.fetched, label: 'Postings fetched from Reed and Adzuna' },
    { key: 'unique', count: p.canonical, label: 'Left after removing the same role listed on both boards' },
    { key: 'in_domain', count: p.in_domain, label: 'Actually data roles, after the relevance gate' },
    { key: 'above', count: profile.above_threshold, label: `Scored ${p.shortlist_threshold} or more for a junior ${profile.name.replace(/^Junior\s+/i, '').toLowerCase()}` },
    { key: 'shortlist', count: profile.shortlist.length, label: 'Made the weekly shortlist, one slot per employer and role' },
  ]
  const first = funnel[0].count
  const last = funnel[funnel.length - 1].count
  const widest = Math.max(...funnel.map((f) => f.count), 1)

  const inDomainRoles = s.roles.length
  const full = s.roles.filter((r) => r.confidence === 'full').length
  const excerpts = inDomainRoles - full
  const described = inDomainRoles || 1

  const seniorityCounts: Record<string, number> = {}
  for (const r of s.roles) {
    const k = r.seniority ?? 'not stated'
    seniorityCounts[k] = (seniorityCounts[k] ?? 0) + 1
  }
  const seniority = SENIORITY_ORDER
    .filter((k) => seniorityCounts[k])
    .map((k) => ({ key: k, n: seniorityCounts[k] }))
  const seniorityMax = Math.max(...seniority.map((x) => x.n), 1)

  const reasons = new Map<string, string[]>()
  for (const e of p.excluded) {
    reasons.set(e.reason, [...(reasons.get(e.reason) ?? []), e.title])
  }

  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <h1 id="hero-title">
          {num(first)} UK data postings went in this week. {num(last)} came out.
        </h1>
        <p className="lead">
          Six agents read the job market every Monday, discard what does not belong,
          score what is left against a candidate profile and send a shortlist.
          This is what happened in the latest run.
        </p>
        <p className="stamp">
          Run of {longDate(s.generated_at)}. Change the profile above and the last two steps change with it.
        </p>

        <ol className="funnel" aria-label="How the postings were narrowed down">
          {funnel.map((f, i) => (
            <li key={f.key} className="funnel-row" style={{ ['--i' as string]: i }}>
              <span className="funnel-step" aria-hidden="true">{i + 1}</span>
              <span className="funnel-count">{num(f.count)}</span>
              <div className="funnel-track">
                <div className="funnel-bar" style={{ width: `${Math.max((f.count / widest) * 100, 2)}%` }} />
              </div>
              <span className="funnel-label">{f.label}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="section" aria-labelledby="quality">
        <h2 id="quality">What the pipeline had to work with</h2>
        <p className="intro">
          Reed returns a complete description for each posting, fetched one by one from its
          detail endpoint. Adzuna returns only a short excerpt. An excerpt can say a role
          wants Python, but never that it does not, so those postings are scored without
          comparing skills and ranked below every fully analysed role.
        </p>

        <div className="two-col">
          <div>
            <h3>Full descriptions against excerpts</h3>
            <div className="proportion" role="img"
                 aria-label={`${full} full descriptions and ${excerpts} excerpts`}>
              <div className="full" style={{ width: `${(full / described) * 100}%` }} />
              <div className="part" style={{ width: `${(excerpts / described) * 100}%` }} />
            </div>
            <div className="legend">
              <div><span className="swatch" style={{ background: 'var(--ink)' }} />
                {num(full)} with a full description, scored on every factor</div>
              <div><span className="swatch" style={{ background: 'var(--grey)' }} />
                {num(excerpts)} excerpts only, scored provisionally</div>
            </div>
          </div>

          <div>
            <h3>Seniority asked for</h3>
            <div className="hbars" style={{ marginTop: '0.9rem' }}>
              {seniority.map(({ key, n }) => (
                <div className="hbar" key={key}>
                  <span className="hbar-label">{capitalise(key)}</span>
                  <div className="hbar-track">
                    <div className="hbar-fill" style={{ width: `${(n / seniorityMax) * 100}%` }} />
                  </div>
                  <span className="hbar-value">{num(n)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="cleaning">
        <h2 id="cleaning">Cleaning up before scoring</h2>
        <p className="intro">
          The same role often appears on both job boards, and one employer will list an
          identical role in several places. Neither should take more than one slot.
        </p>
        <div className="facts">
          <div className="fact">
            <strong>{num(p.duplicates)}</strong>
            <span>listings removed as the same role on both boards</span>
          </div>
          <div className="fact">
            <strong>{num(s.roles.reduce((n, r) => n + r.also_listed_in.length, 0))}</strong>
            <span>repeat listings folded into one, keeping every location</span>
          </div>
          <div className="fact">
            <strong>{num(p.out_of_domain)}</strong>
            <span>postings turned away as not really data roles</span>
          </div>
          <div className="fact">
            <strong>{p.salary.median_minimum ? money(p.salary.median_minimum) : 'n/a'}</strong>
            <span>median advertised minimum, from {num(p.salary.stated_count)} stated salaries</span>
          </div>
        </div>
      </section>

      {reasons.size > 0 && (
        <section className="section" aria-labelledby="gate">
          <h2 id="gate">What the relevance gate turned away</h2>
          <p className="intro">
            Keyword search returns roles that only mention the search terms. A creative
            director role full of the word AI matches a search for data scientist, but
            scoring it against a data profile would mean nothing. The job title decides first.
          </p>
          <div className="exclusions">
            {[...reasons.entries()].map(([reason, titles]) => (
              <div className="exclusion" key={reason}>
                <h3>{capitalise(reason)}</h3>
                <p>{titles.slice(0, 4).join(', ')}{titles.length > 4 && `, and ${titles.length - 4} more`}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="section" aria-label="Explore further">
        <div className="nexts four">
          <div className="next">
            <h3><Link to="/roles">Browse the {num(s.roles.length)} roles</Link></h3>
            <p>Filter by seniority and score, and see exactly why each one scored as it did.</p>
          </div>
          <div className="next">
            <h3><Link to="/skills">See which skills are asked for</Link></h3>
            <p>How often each skill appears, and how often it is stated as essential.</p>
          </div>
          <div className="next">
            <h3><Link to="/your-cv">Score your own CV</Link></h3>
            <p>Upload it and see your matches. It is read in your browser and never uploaded.</p>
          </div>
          <div className="next">
            <h3><Link to="/how-it-works">Read how it works</Link></h3>
            <p>The six agents, the deployment, and twelve bugs found by running it for real.</p>
          </div>
        </div>
      </section>
    </>
  )
}
