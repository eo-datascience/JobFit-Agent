// Scoring a visitor's own CV, in their browser.
//
// The arithmetic here mirrors agents/scoring.py. Everything that can be shared
// is shared instead of copied: the taxonomy, the skill categories and the
// weights all arrive in the snapshot, and a Python test asserts they still
// match the ones the weekly agent uses. Only the calculation is reimplemented,
// which keeps the two from drifting apart quietly.
//
// Nothing leaves the browser. The CV is read, matched and scored here, and is
// never uploaded, stored or sent anywhere.

import type { Role, Rules } from './types'

export interface VisitorProfile {
  skills: string[]
  seniority: string
  locations: string[]
  openToRemote: boolean
  minimumSalary: number | null
}

export interface Breakdown {
  name: string
  score: number
  weight: number
  detail: string
}

export interface VisitorScore {
  total: number
  provisional: boolean
  components: Breakdown[]
  matched: string[]
  partial: string[]
  missingEssential: string[]
}

/** Escape a string for use inside a regular expression. */
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Find taxonomy skills in free text, matching whole words only.
 *
 * Longest aliases first, so "google cloud platform" is not shadowed by a
 * shorter overlapping one. The boundaries exclude + and # so that C++ and C#
 * survive, which is the same rule the extraction agent applies.
 */
export function findSkills(text: string, rules: Rules): string[] {
  if (!text.trim()) return []
  const found = new Set<string>()
  const aliases = Object.keys(rules.aliases).sort((a, b) => b.length - a.length)

  for (const alias of aliases) {
    const canonical = rules.aliases[alias]
    if (found.has(canonical)) continue
    const pattern = new RegExp(`(?<![\\w+#])${escape(alias)}(?![\\w+#])`, 'i')
    if (pattern.test(text)) found.add(canonical)
  }
  return [...found].sort()
}

/** Guess a seniority from the wording of a CV, defaulting to mid. */
export function guessSeniority(text: string): string {
  const t = text.toLowerCase()
  if (/\b(head of|principal|director|vp|chief|tech lead|team lead)\b/.test(t)) return 'lead'
  if (/\bsenior\b/.test(t)) return 'senior'
  if (/\b(graduate|junior|trainee|intern|placement|entry level)\b/.test(t)) return 'junior'
  return 'mid'
}

function scoreSkills(profile: VisitorProfile, role: Role, rules: Rules) {
  if (role.skills.length === 0) {
    return { score: 0, matched: [], partial: [], missingEssential: [], detail: 'no skills stated' }
  }
  const have = new Set(profile.skills)
  const categories = new Set(
    profile.skills.map((s) => rules.categories[s]).filter(Boolean) as string[],
  )

  const matched: string[] = []
  const partial: string[] = []
  const missingEssential: string[] = []
  let earned = 0
  let possible = 0

  for (const skill of role.skills) {
    const weight = skill.essential ? rules.essential_multiplier : 1
    possible += weight
    const category = rules.categories[skill.name]

    if (have.has(skill.name)) {
      earned += weight
      matched.push(skill.name)
    } else if (category && categories.has(category)) {
      earned += weight * rules.category_match_credit
      partial.push(skill.name)
    } else if (skill.essential) {
      missingEssential.push(skill.name)
    }
  }

  let detail = `${matched.length} of ${role.skills.length} skills matched directly`
  if (partial.length) detail += `, ${partial.length} by related experience`
  if (missingEssential.length) detail += `, missing essential: ${missingEssential.join(', ')}`

  return { score: possible ? earned / possible : 0, matched, partial, missingEssential, detail }
}

function scoreSeniority(profile: VisitorProfile, role: Role, rules: Rules): [number, string] {
  if (!role.seniority) return [0.6, 'level not stated, treated as neutral']
  const roleRank = rules.seniority_order.indexOf(role.seniority)
  if (roleRank < 0) return [0.6, 'level not recognised, treated as neutral']
  const mine = Math.max(rules.seniority_order.indexOf(profile.seniority), 0)
  const gap = roleRank - mine

  if (gap === 0) return [1, `${role.seniority} matches your level`]
  if (gap === 1) return [0.75, `${role.seniority} is one step up, a reasonable stretch`]
  if (gap === -1) return [0.5, `${role.seniority} is one step below your level`]
  if (gap > 1) return [0.2, `${role.seniority} is ${gap} levels above your experience`]
  return [0.25, `${role.seniority} is ${Math.abs(gap)} levels below your experience`]
}

function scoreSalary(profile: VisitorProfile, role: Role): [number, string] {
  if (profile.minimumSalary === null) return [0.6, 'you set no salary floor, so pay is not judged against one']
  if (role.salary_min === null && role.salary_max === null) return [0.5, 'salary not advertised']

  const top = role.salary_max ?? role.salary_min ?? 0
  const cap = role.salary_is_predicted ? 0.8 : 1
  const source = role.salary_is_predicted ? 'estimated' : 'advertised'

  if (top >= profile.minimumSalary * 1.2) return [cap, `${source} salary comfortably above your floor`]
  if (top >= profile.minimumSalary) return [cap * 0.8, `${source} salary meets your floor`]
  if (top >= profile.minimumSalary * 0.9) return [cap * 0.4, `${source} salary slightly below your floor`]
  return [0, `${source} salary below your floor`]
}

function scoreLocation(profile: VisitorProfile, role: Role, rules: Rules): [number, string] {
  if (!role.location) return [0.5, 'location not stated']
  const lowered = role.location.toLowerCase()

  if (profile.openToRemote && rules.remote_markers.some((m) => lowered.includes(m))) {
    return [1, 'remote, which you are open to']
  }
  for (const preferred of profile.locations) {
    if (preferred && lowered.includes(preferred.toLowerCase())) return [1, `in ${preferred}`]
  }
  return [0.2, `${role.location} is outside your preferred areas`]
}

/**
 * Score one role for this visitor.
 *
 * On an excerpt only posting the skills component is dropped and its weight
 * spread across the others, exactly as the agent does, and the result is
 * marked provisional so it is never ranked against a fully analysed role.
 */
export function scoreRole(profile: VisitorProfile, role: Role, rules: Rules): VisitorScore {
  const provisional = role.confidence !== 'full'
  const skills = scoreSkills(profile, role, rules)
  const [seniority, seniorityDetail] = scoreSeniority(profile, role, rules)
  const [salary, salaryDetail] = scoreSalary(profile, role)
  const [location, locationDetail] = scoreLocation(profile, role, rules)

  let weights: Record<string, number> = { ...rules.weights }
  if (provisional) {
    const skillsWeight = weights.skills
    const rest = Object.entries(weights).filter(([k]) => k !== 'skills')
    const remaining = rest.reduce((n, [, v]) => n + v, 0)
    weights = Object.fromEntries(rest.map(([k, v]) => [k, v + (v / remaining) * skillsWeight]))
  }

  const components: Breakdown[] = []
  if (!provisional) components.push({ name: 'skills', score: skills.score, weight: weights.skills, detail: skills.detail })
  components.push({ name: 'seniority', score: seniority, weight: weights.seniority, detail: seniorityDetail })
  components.push({ name: 'salary', score: salary, weight: weights.salary, detail: salaryDetail })
  components.push({ name: 'location', score: location, weight: weights.location, detail: locationDetail })

  return {
    total: Math.round(components.reduce((n, c) => n + c.score * c.weight, 0) * 100),
    provisional,
    components,
    matched: skills.matched,
    partial: skills.partial,
    missingEssential: skills.missingEssential,
  }
}

/** Rank every role for this visitor, keeping provisional scores below the rest. */
export function rankRoles(profile: VisitorProfile, roles: Role[], rules: Rules) {
  return roles
    .map((role) => ({ role, fit: scoreRole(profile, role, rules) }))
    .sort((a, b) => {
      if (a.fit.provisional !== b.fit.provisional) return a.fit.provisional ? 1 : -1
      return b.fit.total - a.fit.total
    })
}
