// Parity between the two scorers.
//
// Scoring exists twice: in Python for the weekly agent, and here so a visitor's
// CV can be scored in their own browser without ever uploading it. Two hand
// written implementations drift, and drift here is invisible, because both
// sides carry on returning plausible numbers.
//
// So Python scores a set of deliberately awkward cases and writes the answers
// into parity.json. These tests assert this implementation reproduces them
// exactly. Change the scoring rules on either side without mirroring them and
// this fails.
//
// Regenerate the fixtures with: python scripts/make_parity_fixtures.py

import { describe, expect, it } from 'vitest'
import fixtures from './__fixtures__/parity.json'
import { findSkills, guessSeniority, rankRoles, scoreRole, type VisitorProfile } from './scoring'
import type { Role, Rules } from './types'

const rules = fixtures.rules as unknown as Rules

/** Build the minimum of a Role that the scorer actually reads. */
function asRole(role: (typeof fixtures.cases)[number]['role'], id = '1'): Role {
  return {
    id,
    source: 'reed',
    title: 'Test role',
    company: 'Test employer',
    location: role.location,
    salary_min: role.salary_min,
    salary_max: role.salary_max,
    salary_is_predicted: role.salary_is_predicted,
    url: null,
    posted_at: null,
    confidence: role.confidence as 'full' | 'partial',
    seniority: role.seniority,
    years_experience: null,
    skills: role.skills,
    domain: 'data',
    outcome_key: `reed:${id}`,
    scores: {},
    also_listed_in: [],
  }
}

describe('the browser scorer matches the Python agent', () => {
  it.each(fixtures.cases.map((c) => [c.name, c] as const))('%s', (_name, testCase) => {
    const profile = testCase.profile as VisitorProfile
    const result = scoreRole(profile, asRole(testCase.role), rules)
    const expected = testCase.expected

    expect(result.total).toBe(expected.total)
    expect(result.provisional).toBe(expected.provisional)
    expect(result.matched).toEqual(expected.matched)
    expect(result.partial).toEqual(expected.partial)
    expect(result.missingEssential).toEqual(expected.missingEssential)

    // Component by component, so a failure says which part disagreed rather
    // than only that the total was wrong.
    expect(result.components.map((c) => c.name)).toEqual(expected.components.map((c) => c.name))
    for (const [i, component] of result.components.entries()) {
      expect(component.score).toBeCloseTo(expected.components[i].score, 6)
      expect(component.weight).toBeCloseTo(expected.components[i].weight, 6)
    }
  })

  it('covers every branch that could be mirrored wrongly', () => {
    // A guard on the fixtures themselves. If someone trims the cases down, the
    // suite would still pass while testing almost nothing.
    expect(fixtures.cases.length).toBeGreaterThanOrEqual(14)
    const names = fixtures.cases.map((c) => c.name).join(' ')
    for (const branch of ['essential', 'related experience', 'level up', 'below',
                          'estimated salary', 'remote', 'provisional']) {
      expect(names).toContain(branch)
    }
  })
})

describe('reading skills out of CV text', () => {
  it('finds skills written in any of their usual forms', () => {
    const found = findSkills('Built models with sklearn and deployed on k8s using Postgres.', rules)
    expect(found).toContain('scikit-learn')
    expect(found).toContain('Kubernetes')
    expect(found).toContain('PostgreSQL')
  })

  it('never invents a skill that is not in the text', () => {
    const found = findSkills('Wrote reports in Excel for the finance team.', rules)
    expect(found).toEqual(['Excel'])
  })

  it('does not read R out of research and development', () => {
    // The same guard the extraction agent carries, for the same reason.
    expect(findSkills('Worked with the R&D team on go live planning.', rules)).not.toContain('R')
    expect(findSkills('Worked with the R&D team on go live planning.', rules)).not.toContain('Go')
  })

  it('still finds R when it is written unambiguously', () => {
    expect(findSkills('Statistical work in R programming and Python.', rules)).toContain('R')
  })

  it('returns nothing for empty text rather than throwing', () => {
    expect(findSkills('   ', rules)).toEqual([])
  })
})

describe('guessing a level from CV wording', () => {
  it.each([
    ['Graduate data analyst seeking a first role', 'junior'],
    ['Senior data engineer with eight years', 'senior'],
    ['Head of Data for a retail group', 'lead'],
    ['Data analyst working on reporting', 'mid'],
  ])('%s', (text, expected) => {
    expect(guessSeniority(text)).toBe(expected)
  })
})

describe('ranking', () => {
  const profile: VisitorProfile = {
    skills: ['Python', 'SQL'],
    seniority: 'junior',
    locations: ['London'],
    openToRemote: true,
    minimumSalary: null,
  }

  it('keeps provisional scores below fully analysed ones however high they are', () => {
    const base = fixtures.cases[0].role
    const full = asRole({ ...base, confidence: 'full', skills: [{ name: 'Airflow', essential: true }] }, 'full')
    const provisional = asRole({ ...base, confidence: 'partial', skills: [] }, 'prov')

    const ranked = rankRoles(profile, [provisional, full], rules)

    expect(ranked[0].role.id).toBe('full')
    // The provisional score is genuinely the higher number, which is exactly
    // why it must not be allowed to outrank.
    expect(ranked[1].fit.total).toBeGreaterThan(ranked[0].fit.total)
  })
})
