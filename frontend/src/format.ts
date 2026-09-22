const gbp = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 })
const count = new Intl.NumberFormat('en-GB')

export const money = (n: number) => gbp.format(n)
export const num = (n: number) => count.format(n)

export function salaryRange(min: number | null, max: number | null): string | null {
  if (!min && !max) return null
  if (min && max && min !== max) return `${money(min)} to ${money(max)}`
  return money((min ?? max) as number)
}

export function longDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

export function daysAgo(iso: string | null, from: string): string | null {
  if (!iso) return null
  const days = Math.round((new Date(from).getTime() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return 'Posted today'
  if (days === 1) return 'Posted yesterday'
  if (days < 14) return `Posted ${days} days ago`
  return `Posted ${Math.round(days / 7)} weeks ago`
}

export const sourceName = (s: string) => (s === 'reed' ? 'Reed' : s === 'adzuna' ? 'Adzuna' : s)

export function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
