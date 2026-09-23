"""The fields this system understands.

The weekly digest only ever reads the data field. It stays exactly as narrow as
it was: four queries, full descriptions, forecasting, learning from outcomes.

The other fields exist so that a visitor to the public site can score their own
CV against real roles in their line of work. They are fetched shallower, they
never reach the digest, and nothing is forecast from them. That asymmetry is
deliberate and the site says so.

A field is defined by three things: the queries that find its postings, the
title tokens that identify one, and the skills that are characteristic of it.
The skills are shared across fields rather than duplicated, because a Python
role is a Python role whichever field advertises it. Only the signature lists
differ, and those are used to place a posting when its title is unhelpful.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Domain:
    id: str
    label: str
    # What the site tells a visitor this field covers.
    blurb: str
    queries: list[str]
    title_tokens: list[str]
    # Skills that place a posting in this field when its title does not.
    signature: list[str] = field(default_factory=list)


DATA = Domain(
    id="data",
    label="Data and analytics",
    blurb="Data science, data engineering, analytics and machine learning roles.",
    queries=["data scientist", "data engineer", "machine learning engineer", "data analyst"],
    title_tokens=[
        "data scientist", "data engineer", "data analyst", "data architect",
        "analytics engineer", "machine learning", "ml engineer", "mlops",
        "ai engineer", "research scientist", "quantitative", "statistician",
        "business intelligence", "bi developer", "bi analyst", "big data",
        "data platform", "data science", "analytics", "etl developer",
        "data warehouse", "data governance", "insight analyst",
    ],
    signature=["Python", "SQL", "pandas", "Machine Learning", "ETL", "Airflow",
               "Power BI", "Tableau", "scikit-learn", "dbt", "Snowflake", "Statistics"],
)

SOFTWARE = Domain(
    id="software",
    label="Software engineering",
    blurb="Backend, frontend and full stack engineering roles.",
    queries=["software engineer", "backend developer", "frontend developer"],
    title_tokens=[
        "software engineer", "software developer", "backend engineer",
        "backend developer", "frontend engineer", "frontend developer",
        "full stack", "fullstack", "web developer", "mobile developer",
        "ios developer", "android developer", "platform engineer", "devops",
        "site reliability", "sre", "engineering manager", "tech lead",
        "application developer", "systems engineer", "api developer",
    ],
    signature=["React", "TypeScript", "Node.js", "Java", "C#", ".NET", "Spring",
               "Microservices", "GraphQL", "Kubernetes", "System Design", "Vue"],
)

PRODUCT = Domain(
    id="product",
    label="Product",
    blurb="Product management, product ownership and delivery roles.",
    queries=["product manager", "product owner"],
    title_tokens=[
        "product manager", "product owner", "product lead", "head of product",
        "product director", "associate product", "technical product",
        "delivery manager", "scrum master", "business analyst",
        "product analyst", "programme manager", "project manager",
    ],
    signature=["Roadmapping", "User Stories", "Backlog Management", "Product Strategy",
               "Stakeholder Management", "User Research", "Discovery", "OKRs",
               "Prioritisation", "Jira", "Agile", "Go To Market"],
)

DOMAINS: dict[str, Domain] = {d.id: d for d in (DATA, SOFTWARE, PRODUCT)}

# The field the weekly digest reads. Everything else exists for the site.
PRIMARY_DOMAIN = DATA.id

# Titles that belong to none of the fields above, however many technology words
# their description happens to contain.
OUT_OF_SCOPE_TITLES: list[str] = [
    "creative director", "art director", "copywriter", "graphic designer",
    "marketing manager", "marketing executive", "brand manager", "social media",
    "content creator", "recruiter", "recruitment consultant", "talent acquisition",
    "sales executive", "account manager", "business development", "customer success",
    "teacher", "tutor", "lecturer", "nurse", "care assistant",
    "paralegal", "solicitor", "accountant", "bookkeeper",
]

# How many signature skills a posting needs before its skills alone decide the
# field. One shared skill means nothing: almost every field mentions SQL.
MIN_SIGNATURE_MATCHES = 2


def classify_domain(title: str, skills: list[str]) -> tuple[str | None, str]:
    """Decide which field a posting belongs to, and say why.

    The title decides first, and the earliest matching token wins, because the
    leading words of a job title carry its field: "data platform engineer" is
    placed by "data platform" rather than by "platform engineer". Length is
    the tiebreak when two tokens start in the same place. When no title matches, the extracted skills decide,
    but only if enough of one field's signature appears. Anything left over is
    outside every field this system covers.

    Returning the reason means an exclusion can be explained on the site rather
    than silently applied.
    """
    lowered = f" {' '.join(title.lower().split())} "

    for token in OUT_OF_SCOPE_TITLES:
        if token in lowered:
            return None, f"title indicates a {token} role"

    best: tuple[int, int, str] | None = None
    for domain in DOMAINS.values():
        for token in domain.title_tokens:
            at = lowered.find(token)
            if at == -1:
                continue
            candidate = (at, -len(token), domain.id)
            if best is None or candidate < best:
                best = candidate
    if best:
        return best[2], f"title matches {DOMAINS[best[2]].label.lower()}"

    held = set(skills)
    counts = {d.id: len(held & set(d.signature)) for d in DOMAINS.values()}
    top = max(counts, key=lambda k: counts[k])
    if counts[top] >= MIN_SIGNATURE_MATCHES:
        matched = sorted(held & set(DOMAINS[top].signature))[:3]
        return top, f"skills point to {DOMAINS[top].label.lower()} ({', '.join(matched)})"

    return None, "no recognised job title and too few skills to place it"


def all_queries() -> dict[str, list[str]]:
    """Search queries per field, for the wider sweep the site is built from."""
    return {d.id: list(d.queries) for d in DOMAINS.values()}
