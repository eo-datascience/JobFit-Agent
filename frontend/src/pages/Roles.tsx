import { Link, useSearchParams } from 'react-router-dom'
import { useMemo } from 'react'
import { useProfile, useSnapshot } from '../data'
import { capitalise, daysAgo, num, salaryRange } from '../format'
import type { ProfileScore, Role } from '../types'

const SENIORITY = ['junior', 'mid', 'senior', 'lead']
type Sort = 'score' | 'newest' | 'salary'

function matches(role: Role, q: string): boolean {
  if (!q) return true
  const hay = [role.title, role.company ?? '', role.location ?? '', ...role.skills.map((s) => s.name)]
    .join(' ').toLowerCase()
  return q.toLowerCase().split(/\s+/).every((word) => hay.includes(word))
}

type Scored = Role & { fit: ProfileScore }

function compare(sort: Sort) {
  return (a: Scored, b: Scored) => {
    if (sort === 'newest') return (b.posted_at ?? '').localeCompare(a.posted_at ?? '')
    if (sort === 'salary') return (b.salary_min ?? 0) - (a.salary_min ?? 0)
    // Score order keeps fully analysed roles above provisional ones, because a
    // provisional score is not comparable with a real one.
    if (a.fit.provisional !== b.fit.provisional) return a.fit.provisional ? 1 : -1
    return b.fit.total - a.fit.total
  }
}

export default function Roles() {
  const s = useSnapshot()
  const { profile } = useProfile()
  const [params, setParams] = useSearchParams()

  const q = params.get('q') ?? ''
  const level = params.get('level') ?? ''
  const fullOnly = params.get('full') === '1'
  const min = Number(params.get('min') ?? 0)
  const sort = (params.get('sort') as Sort) || 'score'

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    setParams(next, { replace: true })
  }

  const shown = useMemo(() => s.roles
    // Only the field the chosen profile belongs to. Mixing fields would put
    // product roles in a data analyst's list, scored on a taxonomy that does
    // not describe them.
    .filter((r) => r.domain === profile.domain)
    .map((r): Scored => ({ ...r, fit: r.scores[profile.id] }))
    .filter((r) => r.fit !== undefined)
    .filter((r) => matches(r, q))
    .filter((r) => !level || (level === 'unstated' ? !r.seniority : r.seniority === level))
    .filter((r) => !fullOnly || !r.fit.provisional)
    .filter((r) => r.fit.total >= min)
    .sort(compare(sort)), [s.roles, profile.id, profile.domain, q, level, fullOnly, min, sort])

  const shortlisted = new Set(profile.shortlist)

  return (
    <>
      <header className="page-head">
        <h1>This week's roles</h1>
        <p className="lead">
          Every {(s.domains.find((d) => d.id === profile.domain)?.label ?? '').toLowerCase()} role
          from the latest run, scored out of 100 for a junior{' '}
          {profile.name.replace(/^Junior\s+/i, '').toLowerCase()}. Grey scores are provisional:
          only an excerpt was available, so skills could not be compared.
        </p>
      </header>

      <div className="filters" role="search">
        <div className="field">
          <label htmlFor="q">Search titles, employers and skills</label>
          <input id="q" type="search" value={q} placeholder="For example, dbt London"
                 onChange={(e) => update('q', e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="level">Seniority</label>
          <select id="level" value={level} onChange={(e) => update('level', e.target.value)}>
            <option value="">Any level</option>
            {SENIORITY.map((l) => <option key={l} value={l}>{capitalise(l)}</option>)}
            <option value="unstated">Not stated</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="sort">Sort by</label>
          <select id="sort" value={sort} onChange={(e) => update('sort', e.target.value === 'score' ? '' : e.target.value)}>
            <option value="score">Best match</option>
            <option value="newest">Most recent</option>
            <option value="salary">Highest salary</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="min">Minimum score: {min}</label>
          <input id="min" type="range" min={0} max={100} step={5} value={min}
                 onChange={(e) => update('min', e.target.value === '0' ? '' : e.target.value)} />
        </div>
        <label className="check">
          <input type="checkbox" checked={fullOnly} onChange={(e) => update('full', e.target.checked ? '1' : '')} />
          Fully analysed only
        </label>
      </div>

      <p className="results-line" aria-live="polite">
        Showing {num(shown.length)} of {num(s.roles.filter((r) => r.domain === profile.domain).length)}{' '}
        {(s.domains.find((d) => d.id === profile.domain)?.label ?? '').toLowerCase()} roles
      </p>

      {shown.length === 0 ? (
        <div className="empty">
          <h2>No roles match these filters</h2>
          <p className="muted">
            Try lowering the minimum score or clearing the search.{' '}
            <Link to="/roles">Show all roles</Link>
          </p>
        </div>
      ) : (
        <ul className="roles">
          {shown.map((r) => {
            const salary = salaryRange(r.salary_min, r.salary_max)
            const posted = daysAgo(r.posted_at, s.generated_at)
            return (
              <li className="role" key={r.id}>
                <div>
                  <div className={`score${r.fit.provisional ? ' provisional' : ''}`}>{r.fit.total}</div>
                  {r.fit.provisional && <div className="score-note">provisional</div>}
                </div>
                <div>
                  <h2><Link to={`/roles/${r.id}`}>{r.title}</Link></h2>
                  <p className="where">
                    {[r.company, r.location].filter(Boolean).join(', ')}
                    {r.also_listed_in.length > 0 && ` and ${r.also_listed_in.length} other location${r.also_listed_in.length > 1 ? 's' : ''}`}
                  </p>
                  {posted && <p className="where small">{posted}</p>}
                  {(r.fit.matched.length > 0 || r.fit.missing_essential.length > 0) && (
                    <div className="chips">
                      {r.fit.matched.slice(0, 6).map((m) => <span className="chip have" key={m}>{m}</span>)}
                      {r.fit.missing_essential.map((m) => <span className="chip gap" key={m}>{m}</span>)}
                    </div>
                  )}
                  {shortlisted.has(r.id) && <p className="small muted" style={{ marginTop: '0.6rem' }}>On this week's shortlist</p>}
                </div>
                <div className="salary">
                  {salary ?? <span className="muted">Salary not stated</span>}
                  {salary && r.salary_is_predicted && <span className="est">estimated by Adzuna</span>}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <div className="key">
        <span><span className="chip have">Skill</span> the profile has it</span>
        <span><span className="chip gap">Skill</span> stated as essential, missing from the profile</span>
      </div>
    </>
  )
}
