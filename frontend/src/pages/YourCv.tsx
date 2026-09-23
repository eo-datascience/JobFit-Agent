import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useProfile, useSnapshot } from '../data'
import { ACCEPTED, MIN_READABLE_CHARS, ReadError, readCv } from '../cvFile'
import { findSkills, guessSeniority, rankRoles, type VisitorProfile } from '../scoring'
import { SAMPLE_CV, SAMPLE_CV_NAME } from '../content/sampleCv'
import { capitalise, num, salaryRange } from '../format'

const LEVELS = ['junior', 'mid', 'senior', 'lead']
const SHOWN = 15

export default function YourCv() {
  const s = useSnapshot()
  const { profile } = useProfile()
  const rules = s.scoring
  // Scored against the field chosen at the top of the page, so a product CV is
  // compared with product roles rather than with data ones.
  const field = s.domains.find((d) => d.id === profile.domain)
  const roles = useMemo(() => s.roles.filter((r) => r.domain === profile.domain),
                        [s.roles, profile.domain])
  const fileInput = useRef<HTMLInputElement>(null)

  const [reading, setReading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [skills, setSkills] = useState<string[] | null>(null)
  const [seniority, setSeniority] = useState('junior')
  const [location, setLocation] = useState('London')
  const [remote, setRemote] = useState(true)
  const [floor, setFloor] = useState('')

  /** Load the text of a CV, from a file or from the bundled sample. */
  function useText(text: string, source: string) {
    const found = findSkills(text, rules)
    setSkills(found)
    setSeniority(guessSeniority(text))
    setFileName(source)
    setError(null)
    return found
  }

  function loadSample() {
    useText(SAMPLE_CV, SAMPLE_CV_NAME)
  }

  async function handleFile(file: File | undefined) {
    if (!file) return
    setReading(true)
    setError(null)
    try {
      const text = await readCv(file)
      const found = useText(text, file.name)
      // Two very different problems produce no skills, and blaming the wrong
      // one sends people off to fix something that was never broken.
      if (text.trim().length < MIN_READABLE_CHARS) {
        setError(
          'Hardly any text could be read from that file. If it is a scanned PDF the words are ' +
          'an image rather than text. Try a Word file, or add your skills by hand below.',
        )
      } else if (found.length === 0) {
        setError(
          'That file was read fine, but none of the skills this system tracks appear in it. ' +
          'It only knows tools used in data and analytics work, so a CV from another field ' +
          'will find nothing here. You can still add skills by hand below to see how the ' +
          'scoring works.',
        )
      }
    } catch (err) {
      setError(err instanceof ReadError ? err.message : 'That file could not be read.')
    } finally {
      setReading(false)
    }
  }

  const cvProfile: VisitorProfile | null = useMemo(() => skills && ({
    skills,
    seniority,
    locations: location.trim() ? [location.trim()] : [],
    openToRemote: remote,
    minimumSalary: floor.trim() ? Number(floor.replace(/[^\d]/g, '')) || null : null,
  }), [skills, seniority, location, remote, floor])

  const ranked = useMemo(
    () => (cvProfile ? rankRoles(cvProfile, roles, rules) : []),
    [cvProfile, roles, rules],
  )
  // Counted over fully analysed roles only. Excerpt only postings score highly
  // precisely because their skills are unknown, and they are ranked below, so
  // including them would claim a number of strong matches that contradicts the
  // list underneath it.
  const threshold = s.pipeline.shortlist_threshold
  const strong = ranked.filter((r) => !r.fit.provisional && r.fit.total >= threshold).length
  const strongProvisional = ranked.filter((r) => r.fit.provisional && r.fit.total >= threshold).length

  const toggleSkill = (name: string) =>
    setSkills((current) => current && (current.includes(name)
      ? current.filter((x) => x !== name)
      : [...current, name].sort()))

  const allSkills = useMemo(
    () => [...new Set(Object.values(rules.aliases))].sort(),
    [rules.aliases],
  )

  return (
    <>
      <header className="page-head">
        <h1>Score your own CV</h1>
        <p className="lead">
          Upload your CV and it is scored against this week's {num(roles.length)} real UK{' '}
          {(field?.label ?? '').toLowerCase()} roles, using the same rules the agent uses for its
          owner. Your CV is read in this browser and never uploaded, stored or sent anywhere.
        </p>
        <p className="lead" style={{ marginTop: '0.75rem' }}>
          Change the field at the top of the page to score against a different line of work.
          Outside data, software engineering and product, there is nothing here to match against.
        </p>
      </header>

      <section aria-labelledby="upload">
        <h2 id="upload" style={{ marginBottom: '0.75rem' }}>Choose your CV</h2>
        <div className="upload">
          <input
            ref={fileInput}
            id="cv"
            type="file"
            accept={ACCEPTED}
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
          <label htmlFor="cv" className="upload-button">
            {reading ? 'Reading your CV' : fileName ? 'Choose a different file' : 'Choose a file'}
          </label>
          <button type="button" className="link-button" onClick={loadSample}>
            or try it with a sample CV
          </button>
          <span className="muted small">
            {fileName ?? 'PDF, Word .docx, or plain text. Nothing leaves this page.'}
          </span>
        </div>
        {error && <p className="notice" role="status">{error}</p>}
      </section>

      {skills && (
        <>
          <section className="section" aria-labelledby="found">
            <h2 id="found">What it found</h2>
            <p className="intro">
              Skills are matched word for word, so nothing is guessed. Anything wrong can be
              removed, and anything missed can be added. Everything updates as you change it.
            </p>

            <div className="field" style={{ marginBottom: '1.5rem' }}>
              <span className="label">Your skills, {skills.length} found</span>
              <div className="chips">
                {skills.length === 0 && <span className="muted">None yet. Add some below.</span>}
                {skills.map((k) => (
                  <button type="button" className="chip have removable" key={k}
                          onClick={() => toggleSkill(k)}
                          aria-label={`Remove ${k}`}>
                    {k} <span aria-hidden="true">×</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="filters" style={{ borderBottom: 0 }}>
              <div className="field">
                <label htmlFor="add">Add a skill</label>
                <select id="add" value="" onChange={(e) => e.target.value && toggleSkill(e.target.value)}>
                  <option value="">Choose a skill</option>
                  {allSkills.filter((k) => !skills.includes(k)).map((k) => (
                    <option key={k} value={k}>{k}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="level">Your level</label>
                <select id="level" value={seniority} onChange={(e) => setSeniority(e.target.value)}>
                  {LEVELS.map((l) => <option key={l} value={l}>{capitalise(l)}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="where">Where you want to work</label>
                <input id="where" type="search" value={location} placeholder="For example, Manchester"
                       onChange={(e) => setLocation(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="floor">Lowest salary you would accept</label>
                <input id="floor" type="search" inputMode="numeric" value={floor}
                       placeholder="Leave blank to ignore pay"
                       onChange={(e) => setFloor(e.target.value)} />
              </div>
              <label className="check">
                <input type="checkbox" checked={remote} onChange={(e) => setRemote(e.target.checked)} />
                Open to remote
              </label>
            </div>
          </section>

          {skills.length === 0 ? (
            <section className="section" aria-labelledby="matches">
              <h2 id="matches">Your matches</h2>
              <p className="intro">
                Nothing to score yet. Add at least one skill above and this fills in. Scoring a CV
                with no recognised skills would rank roles on location and salary alone, which
                would say nothing useful about fit.
              </p>
            </section>
          ) : (
          <section className="section" aria-labelledby="matches">
            <h2 id="matches">Your matches</h2>
            <p className="intro">
              {strong > 0
                ? `${strong} fully described roles score ${threshold} or more for you. The strongest are below.`
                : `No fully described role reached ${threshold} this week. The closest are below, with what each one is missing.`}
              {strongProvisional > 0 && ` Another ${strongProvisional} scored above ${threshold} on an excerpt alone, which cannot show whether your skills match, so they rank below the rest.`}
            </p>

            <ul className="roles">
              {ranked.slice(0, SHOWN).map(({ role, fit }) => {
                const salary = salaryRange(role.salary_min, role.salary_max)
                return (
                  <li className="role" key={role.id}>
                    <div>
                      <div className={`score${fit.provisional ? ' provisional' : ''}`}>{fit.total}</div>
                      {fit.provisional && <div className="score-note">provisional</div>}
                    </div>
                    <div>
                      <h3 style={{ fontSize: '1.1rem' }}>
                        <Link to={`/roles/${role.id}`}>{role.title}</Link>
                      </h3>
                      <p className="where">{[role.company, role.location].filter(Boolean).join(', ')}</p>
                      <div className="chips">
                        {fit.matched.slice(0, 6).map((m) => <span className="chip have" key={m}>{m}</span>)}
                        {fit.partial.slice(0, 3).map((m) => <span className="chip related" key={m}>{m}</span>)}
                        {fit.missingEssential.map((m) => <span className="chip gap" key={m}>{m}</span>)}
                      </div>
                    </div>
                    <div className="salary">
                      {salary ?? <span className="muted">Salary not stated</span>}
                    </div>
                  </li>
                )
              })}
            </ul>
            <p className="muted small" style={{ marginTop: '1rem' }}>
              Opening a role shows the sample profile's score for it, not yours, since only this
              page knows your CV.
            </p>
          </section>
          )}
        </>
      )}
    </>
  )
}
