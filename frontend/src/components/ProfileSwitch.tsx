import { useProfile, useSnapshot } from '../data'

// All sample profiles are junior, so the shared prefix is dropped from the
// buttons to keep them short. The full name is still announced.
const short = (name: string) => name.replace(/^Junior\s+/i, '')

export default function ProfileSwitch() {
  const s = useSnapshot()
  const { profile, setProfileId } = useProfile()

  return (
    <div className="profile-bar">
      <div className="frame">
        <fieldset className="profile-switch">
          <legend>Score every role as a junior</legend>
          <div className="segmented">
            {s.profiles.map((p) => (
              <label key={p.id}>
                <input
                  type="radio"
                  name="profile"
                  value={p.id}
                  checked={p.id === profile.id}
                  onChange={() => setProfileId(p.id)}
                  aria-label={p.name}
                />
                <span>{short(p.name)}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <p className="profile-skills">
          Has {profile.skills.join(', ')}.
        </p>
      </div>
    </div>
  )
}
