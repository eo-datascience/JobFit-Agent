import { useProfile, useSnapshot } from '../data'

const short = (name: string) => name.replace(/^Junior\s+/i, '')

export default function ProfileSwitch() {
  const s = useSnapshot()
  const { profile, setProfileId } = useProfile()
  const field = s.domains.find((d) => d.id === profile.domain)

  // Choosing a profile also chooses a field, so there is one control rather
  // than two. The roles on every page follow the field of the profile picked.
  const byField = s.domains
    .map((d) => ({ field: d, profiles: s.profiles.filter((p) => p.domain === d.id) }))
    .filter((g) => g.profiles.length > 0)

  return (
    <div className="profile-bar">
      <div className="frame">
        <div className="field profile-picker">
          <label htmlFor="profile">Score roles as a</label>
          <select id="profile" value={profile.id} onChange={(e) => setProfileId(e.target.value)}>
            {byField.map(({ field: f, profiles }) => (
              <optgroup key={f.id} label={f.label}>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>{short(p.name)}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <p className="profile-skills">
          {field && !field.primary && (
            <><strong>{field.label}</strong> is covered so visitors can try their own CV. It is
            fetched more shallowly than data, which this system follows properly. </>
          )}
          Has {profile.skills.join(', ')}.
        </p>
      </div>
    </div>
  )
}
