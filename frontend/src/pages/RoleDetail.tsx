import { Link, useParams } from 'react-router-dom'
import { useProfile, useSnapshot } from '../data'
import { capitalise, daysAgo, salaryRange, sourceName } from '../format'
import NotFound from './NotFound'

const COMPONENT_NAMES: Record<string, string> = {
  skills: 'Skills',
  seniority: 'Seniority',
  salary: 'Salary',
  location: 'Location',
}

export default function RoleDetail() {
  const { id } = useParams()
  const s = useSnapshot()
  const { profile } = useProfile()
  const role = s.roles.find((r) => r.id === id)
  const fit = role?.scores[profile.id]
  if (!role || !fit) return <NotFound />

  const maxWeight = Math.max(...fit.components.map((c) => c.weight), 0.01)
  const have = new Set(fit.matched)
  const related = new Set(fit.partial)
  const essential = role.skills.filter((k) => k.essential)
  const desirable = role.skills.filter((k) => !k.essential)
  const salary = salaryRange(role.salary_min, role.salary_max)
  const posted = daysAgo(role.posted_at, s.generated_at)

  const chipFor = (name: string, isEssential: boolean) => {
    if (have.has(name)) return 'have'
    if (related.has(name)) return 'related'
    return isEssential ? 'gap' : 'plain'
  }

  const facts = [
    role.seniority ? `${capitalise(role.seniority)} level` : 'Seniority not stated',
    role.years_experience ? `${role.years_experience} years' experience asked for` : null,
    posted,
  ].filter(Boolean)

  return (
    <article>
      <Link to="/roles" className="back">Back to all roles</Link>

      <header className="detail-head">
        <div>
          <h1>{role.title}</h1>
          <p className="detail-where">
            {[role.company, role.location].filter(Boolean).join(', ')}
            {salary && <><br />{salary}{role.salary_is_predicted && ', estimated by Adzuna'}</>}
          </p>
          <p className="muted small" style={{ marginTop: '0.6rem' }}>{facts.join('. ')}.</p>
          {role.also_listed_in.length > 0 && (
            <p className="muted small" style={{ marginTop: '0.4rem' }}>
              The same employer listed this role in {role.also_listed_in.join(', ')} as well.
            </p>
          )}
        </div>
        <div className="detail-score">
          <div className={`score${fit.provisional ? ' provisional' : ''}`}>{fit.total}</div>
          <div className="of">out of 100</div>
        </div>
      </header>

      {fit.provisional && (
        <p className="provisional-note">
          This score is provisional. Only an excerpt of the posting was available, which can
          show that a role wants a skill but never that it does not, so skills were left out
          and their weight spread across the other factors. It is not comparable with a fully
          analysed role, which is why roles like this always rank below them.
        </p>
      )}

      <section className="section" aria-labelledby="why">
        <h2 id="why">Why it scored {fit.total} for a junior {profile.name.replace(/^Junior\s+/i, '').toLowerCase()}</h2>
        <p className="intro">
          The score is the sum of the factors below. Each bar is drawn in proportion to how
          much that factor is worth, and filled by how much of it the role earned. Switch
          profile at the top of the page and every figure here is recalculated.
        </p>
        <div className="breakdown">
          {fit.components.map((c) => {
            const earned = Math.round(c.score * c.weight * 100)
            const available = Math.round(c.weight * 100)
            return (
              <div className="component" key={c.name}>
                <div className="component-top">
                  <span className="component-name">{COMPONENT_NAMES[c.name] ?? capitalise(c.name)}</span>
                  <span className="component-points">{earned} <span className="of">of {available} points</span></span>
                </div>
                <div className="component-track" style={{ width: `${(c.weight / maxWeight) * 100}%` }}>
                  <div className="component-fill" style={{ width: `${c.score * 100}%` }} />
                </div>
                <p className="component-detail">{capitalise(c.detail)}.</p>
              </div>
            )
          })}
        </div>
      </section>

      {role.skills.length > 0 && (
        <section className="section" aria-labelledby="asked">
          <h2 id="asked">Skills the posting asks for</h2>
          <p className="intro">
            Every skill here was matched word for word in the posting, so none of them are
            guessed. Essential and desirable come from the heading each skill sat under.
          </p>
          <div className="skill-cols">
            <div>
              <h3>Essential</h3>
              {essential.length ? (
                <div className="chips">
                  {essential.map((k) => <span className={`chip ${chipFor(k.name, true)}`} key={k.name}>{k.name}</span>)}
                </div>
              ) : <p className="muted">None marked as essential.</p>}
            </div>
            <div>
              <h3>Desirable or unmarked</h3>
              {desirable.length ? (
                <div className="chips">
                  {desirable.map((k) => <span className={`chip ${chipFor(k.name, false)}`} key={k.name}>{k.name}</span>)}
                </div>
              ) : <p className="muted">None.</p>}
            </div>
          </div>
          <div className="key">
            <span><span className="chip have">Skill</span> the profile has it</span>
            <span><span className="chip related">Skill</span> the profile has something closely related</span>
            <span><span className="chip gap">Skill</span> essential and missing</span>
          </div>
        </section>
      )}

      {role.url && (
        <a className="source-link" href={role.url} target="_blank" rel="noopener noreferrer">
          View the original posting on {sourceName(role.source)}
        </a>
      )}

      <p className="muted small" style={{ marginTop: '2.5rem', maxWidth: '62ch' }}>
        Scored against the sample {profile.name.toLowerCase()} profile, with{' '}
        {profile.years_experience} year{profile.years_experience === 1 ? '' : 's'} of experience
        and these skills: {profile.skills.join(', ')}.
      </p>
    </article>
  )
}
