// Mirrors the snapshot written by agents/export.py. If the exporter changes
// shape, these types are where the frontend finds out.

export interface Component {
  name: string
  score: number
  weight: number
  detail: string
}

export interface ProfileScore {
  total: number
  provisional: boolean
  components: Component[]
  matched: string[]
  partial: string[]
  missing_essential: string[]
}

export interface Role {
  id: string
  source: string
  title: string
  company: string | null
  location: string | null
  salary_min: number | null
  salary_max: number | null
  salary_is_predicted: boolean
  url: string | null
  posted_at: string | null
  confidence: 'full' | 'partial'
  seniority: string | null
  years_experience: number | null
  skills: { name: string; essential: boolean }[]
  scores: Record<string, ProfileScore>
  also_listed_in: string[]
}

export interface Profile {
  id: string
  name: string
  seniority: string
  years_experience: number
  skills: string[]
  summary: string
  above_threshold: number
  shortlist: string[]
  repeat_listings: number
}

export interface Demand {
  skill: string
  postings: number
  share: number
  essential_share: number | null
}

export interface Trend {
  skill: string
  trend: 'rising' | 'falling' | 'stable'
  change_pct: number | null
  current: number
}

export interface Rules {
  weights: Record<string, number>
  essential_multiplier: number
  category_match_credit: number
  seniority_order: string[]
  remote_markers: string[]
  aliases: Record<string, string>
  categories: Record<string, string>
}

export interface Snapshot {
  schema_version: number
  is_sample?: boolean
  generated_at: string
  week_of: string
  pipeline: {
    fetched: number
    duplicates: number
    canonical: number
    by_source: Record<string, number>
    full_confidence: number
    partial_confidence: number
    in_domain: number
    out_of_domain: number
    excluded: { title: string; company: string | null; reason: string }[]
    salary: { stated_count: number; median_minimum: number | null }
    shortlist_threshold: number
  }
  scoring: Rules
  profiles: Profile[]
  roles: Role[]
  skills: {
    described: number
    demand: Demand[]
    pairs: { a: string; b: string; postings: number }[]
    weeks_recorded: number
    weeks_needed: number
    trends: Trend[]
  }
}
