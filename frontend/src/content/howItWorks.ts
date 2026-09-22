// Content for the How it works page. Kept apart from the component so the
// writing can be edited without touching layout.

export interface Agent {
  name: string
  body: string
}

export const AGENTS: Agent[] = [
  {
    name: 'Ingestion',
    body: 'Pulls live UK postings from Reed and Adzuna. Reed descriptions are fetched one by one from its detail endpoint, and Adzuna adds breadth and salary data. The same role listed on both boards is kept once, preferring the copy with a full description.',
  },
  {
    name: 'Extraction',
    body: 'Finds the skills each posting asks for by matching a curated taxonomy word for word, so no skill is ever invented. Section headings separate essential from desirable, and roles that are not really data roles are turned away.',
  },
  {
    name: 'Scoring',
    body: 'Scores each posting out of 100 across skills, seniority, salary and location. Related experience earns partial credit through explicit skill families. Postings with only an excerpt are scored provisionally and ranked below the rest.',
  },
  {
    name: 'Forecasting',
    body: 'Tracks the share of postings asking for each skill, week by week. It will not call a trend until it has eight weeks of its own recorded history.',
  },
  {
    name: 'Digest',
    body: 'Emails a shortlist every Monday with no approval step. Nothing is marked as sent until the email has actually gone, and a role one employer lists in several places takes one slot.',
  },
  {
    name: 'Outcome monitor',
    body: 'Learns from real application results. It will not change the scoring weights until it has twenty resolved outcomes, and any change is pulled back toward the original weights and capped.',
  },
]

export interface Bug {
  title: string
  agent: string
  what: string
  why: string
  fix: string
}

export const BUGS: Bug[] = [
  {
    title: 'Most postings could not be parsed',
    agent: 'Ingestion',
    what: 'Only 132 of 307 postings had enough text to extract skills from, far fewer than expected.',
    why: "Reed's search endpoint returns a snippet, not the full description. The complete text sits behind a separate detail endpoint, one request per posting.",
    fix: 'Each Reed posting is now fetched from its detail endpoint, and a posting is only marked as fully described once that call succeeds. Descriptions grew from around 450 characters to around 3,500.',
  },
  {
    title: 'Research and development counted as the R language',
    agent: 'Extraction',
    what: 'R appeared among the most demanded skills.',
    why: 'The single letter r was a valid alias, and in R&D the ampersand passed the word boundary check.',
    fix: 'One and two letter skills now only match unambiguous forms, such as R programming, RStudio or Python/R.',
  },
  {
    title: 'No skill was ever marked essential',
    agent: 'Extraction',
    what: 'Every posting reported no essential skills at all.',
    why: 'The HTML cleaner collapsed all whitespace, line breaks included, so each posting became a single line and no section heading could be found.',
    fix: 'Block level tags such as paragraphs and list items now become line breaks before the tags are stripped.',
  },
  {
    title: 'Then everything became essential',
    agent: 'Extraction',
    what: 'On some postings every skill was marked essential, including tools named under benefits.',
    why: 'An essential section, once opened, ran to the end of the posting.',
    fix: 'Neutral headings such as Benefits, About us and How to apply now close a requirements section.',
  },
  {
    title: 'A creative director was scored as a data role',
    agent: 'Extraction',
    what: 'An AI Creative Director posting came back with no skills at all.',
    why: 'Its description was full of the word AI, so it matched a search for data scientist, but it was a marketing role.',
    fix: 'A relevance gate now checks the job title first. Roles outside the field stay in the market data but are never scored or sent.',
  },
  {
    title: 'Knowing less produced a better score',
    agent: 'Scoring',
    what: 'Two excerpt only postings scored 95 and pushed a role with five of six skills matched down to third place.',
    why: 'With skills unknown, their weight was spread across seniority, salary and location, which are all easy to score highly on.',
    fix: 'Provisional scores now rank in a separate tier and can never outrank a fully analysed role. Tiering was chosen over a discount because the honest claim is that the two are not comparable, not that one is worth some fraction of the other.',
  },
  {
    title: 'Ten real weeks became thirty five',
    agent: 'Forecasting',
    what: 'The first trend report showed skills at zero and rising by 100 percent.',
    why: 'Weeks dropped as too thin were filled back in as zeros, and the run was on a Monday, so the current week held about one day of postings.',
    fix: 'Reconstructed history is no longer gap filled, the week in progress is left out, and the baseline is a three week average.',
  },
  {
    title: 'One posting a week became a 155 percent surge',
    agent: 'Forecasting',
    what: 'Kubernetes was reported as rising 155 percent while appearing in about one posting a week.',
    why: 'The guard against thin data summed percentage shares instead of counting postings, and eight weeks at three percent sums to twenty four.',
    fix: 'The guard now counts real postings, and changes in share are measured in percentage points.',
  },
  {
    title: 'Python was falling twenty points in a month',
    agent: 'Forecasting',
    what: "Python's share was projected to fall from 38 to 18 percent within four weeks.",
    why: 'One week of data was from January. Postings still listed after eight months are the roles nobody could fill, not a fair sample of their week, and the trend line treated January and July as neighbours.',
    fix: 'Reconstruction looks back twelve weeks at most, and trend lines use real elapsed time.',
  },
  {
    title: 'Everything fell, then everything rose',
    agent: 'Forecasting',
    what: 'One run showed every major skill falling. The next showed every one rising.',
    why: 'Excerpts, which name one or two skills, were counted in the denominator. As their share of a week changed, every skill moved with it.',
    fix: 'Only fully described postings now count toward a share, and the report warns when nearly every skill moves the same way at once, since real markets rarely do.',
  },
  {
    title: 'Ten roles sent but never recorded',
    agent: 'Digest',
    what: 'After the first real email, the outcome monitor knew nothing about the ten roles in it.',
    why: 'Roles were marked as sent before the recommendations were recorded, so a failure between the two steps would hide them from both.',
    fix: 'Recommendations are now recorded first. A failure leaves the roles unmarked, so they are simply offered again the following week.',
  },
  {
    title: 'One listing took four of ten slots',
    agent: 'Digest',
    what: 'The same trainee role appeared four times in a ten role shortlist.',
    why: 'One employer listed it in four London postcodes, and each was a separate posting.',
    fix: 'Each employer and role now takes one slot. The other locations are shown on that entry rather than discarded, since one may be far easier to reach.',
  },
]

export const PRINCIPLES = [
  {
    title: 'Nothing is invented',
    body: 'Skills are matched word for word against the posting, so a skill cannot appear unless the text contains it. An optional model pass can add judgements such as seniority, and anything it returns is checked against the posting before it is kept.',
  },
  {
    title: 'Unknown is not the same as zero',
    body: 'An excerpt that never mentions Python is not a role that does not want it. A week too thin to measure is not a week of no demand. Three of the twelve bugs came from treating a missing value as a real one.',
  },
  {
    title: 'Failures stay recoverable',
    body: 'The system acts on its own, so the failures that matter are the ones nobody sees. Each step is ordered so that if it breaks halfway, work is repeated rather than lost.',
  },
  {
    title: 'Private data is kept apart by design',
    body: 'Code lives in a public repository and personal data in a private one. This site scores against a sample profile, and secrets are redacted from every log after an API key once reached one through an error message.',
  },
]
