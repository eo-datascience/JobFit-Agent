"""Generate sample dashboard data for frontend development.

The postings are synthetic and every company name is fictional, but they pass
through the real extraction agent and the real scorer, so the data has exactly
the shape and behaviour the live export produces.

It writes frontend/public/data/sample.json, which is gitignored, rather than
the dashboard.json the site publishes. The site only reads the sample while
running in development and only when no real snapshot exists, so invented
postings can never reach the live site. It is also flagged as sample data, and
the site shows a banner whenever it is in use.

For real data locally, run:

    python run_weekly.py --export-only
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Run as "python scripts/make_sample_data.py" from the project root, the script's
# own folder is on the path but the project root is not, so the agents package
# cannot be found. Adding the root makes the obvious command work.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.export import Profile, build_dashboard
from agents.extraction import extract
from agents.ingestion import Posting

random.seed(7)

COMPANIES = [
    "Northwind Analytics", "Harbourline Bank", "Kestrel Health", "Ashgrove Retail",
    "Meridian Freight", "Larkspur Insurance", "Copperfield Energy", "Tallis Media",
    "Orchard Street Capital", "Brightwater Labs", "Fenwick Logistics", "Saltmarsh Games",
    "Quayside Telecom", "Wexford Pharma", "Palisade Security", "Juniper Travel",
]
LOCATIONS = ["London", "London", "London", "Canary Wharf", "Shoreditch",
             "Hammersmith", "Croydon", "Stratford"]

SOFTWARE_ROLES = [
    ("Junior Software Engineer", ["JavaScript", "Git"], ["React", "Node.js"], 34000),
    ("Backend Engineer", ["Node.js", "REST APIs", "PostgreSQL"], ["Docker", "AWS"], 55000),
    ("Frontend Developer", ["React", "TypeScript", "JavaScript"], ["Testing", "GraphQL"], 48000),
    ("Full Stack Developer", ["TypeScript", "Node.js", "React"], ["Docker", "SQL"], 52000),
    ("Platform Engineer", ["Kubernetes", "Terraform", "AWS"], ["Docker", "CI/CD"], 68000),
]

PRODUCT_ROLES = [
    ("Junior Product Manager", ["User Stories", "Agile"], ["Jira", "SQL"], 35000),
    ("Product Owner", ["Backlog Management", "User Stories", "Stakeholder Management"],
     ["Jira", "Discovery"], 52000),
    ("Product Manager", ["Roadmapping", "Product Strategy", "Prioritisation"],
     ["User Research", "OKRs"], 62000),
    ("Business Analyst", ["Stakeholder Management", "User Stories"], ["SQL", "Agile"], 45000),
]

ROLES = [
    ("Junior Data Analyst", ["SQL", "Excel", "Power BI"], ["Python", "Tableau"], 32000),
    ("Data Analyst", ["SQL", "Tableau", "Statistics"], ["Python", "A/B Testing"], 42000),
    ("Graduate Data Scientist", ["Python", "Machine Learning", "Statistics"],
     ["scikit-learn", "SQL"], 36000),
    ("Data Scientist", ["Python", "scikit-learn", "SQL", "Machine Learning"],
     ["PyTorch", "AWS"], 55000),
    ("Junior Data Engineer", ["Python", "SQL", "ETL"], ["Airflow", "AWS", "Docker"], 38000),
    ("Data Engineer", ["Python", "PySpark", "Airflow", "SQL"],
     ["Databricks", "Kubernetes", "Terraform"], 60000),
    ("Analytics Engineer", ["SQL", "dbt", "Data Modelling"], ["Snowflake", "Python"], 52000),
    ("Machine Learning Engineer", ["Python", "PyTorch", "Docker", "MLflow"],
     ["Kubernetes", "AWS"], 65000),
    ("NLP Engineer", ["Python", "NLP", "Hugging Face"], ["LLMs", "RAG", "Docker"], 62000),
    ("Senior Data Engineer", ["Python", "Apache Spark", "AWS", "Terraform"],
     ["Kafka", "Kubernetes"], 80000),
    ("BI Developer", ["Power BI", "SQL", "Data Modelling"], ["Azure", "Excel"], 45000),
    ("AI Engineer", ["Python", "LLMs", "RAG"], ["Azure", "Docker", "FastAPI"], 70000),
]
OUT_OF_DOMAIN = [
    ("AI Creative Director", "Lead brand campaigns using Adobe Firefly and generative imagery."),
    ("Marketing Manager", "Own our social and paid channels. Python curious a bonus."),
    ("Recruitment Consultant", "Place data professionals with our clients across London."),
]


def _description(title: str, essential: list[str], desirable: list[str], full: bool) -> str:
    if not full:
        return f"{title} role. Strong {essential[0]} skills needed. Apply now."
    return (
        f"{title}\n\n"
        "About the role\n"
        f"You will join a small team working on {random.choice(['pricing', 'fraud', 'forecasting', 'customer', 'supply chain'])} data.\n\n"
        "Essential:\n" + "\n".join(f"Strong experience with {s}." for s in essential) + "\n\n"
        "Desirable:\n" + "\n".join(f"Exposure to {s}." for s in desirable) + "\n\n"
        "Benefits\n25 days holiday, pension and hybrid working.\n"
        + ("Further detail about the team and our approach. " * 12)
    )


def main() -> None:
    postings: list[Posting] = []
    week = date(2026, 9, 21)
    index = 57300000

    # The other fields are fetched shallower in the real run, so the sample
    # reflects that rather than showing an even split.
    for pool, count in ((SOFTWARE_ROLES, 18), (PRODUCT_ROLES, 14)):
        for _ in range(count):
            title, essential, desirable, salary = random.choice(pool)
            full = random.random() < 0.6
            source = "reed" if full else "adzuna"
            index += random.randint(1, 900)
            low = salary + random.choice([-4000, -2000, 0, 3000])
            postings.append(Posting(
                source=source,
                source_job_id=str(index),
                title=title,
                description=_description(title, essential, desirable, full),
                has_full_description=full,
                company=random.choice(COMPANIES),
                location=random.choice(LOCATIONS),
                salary_min=float(low),
                salary_max=float(low + random.choice([6000, 9000, 12000])),
                salary_is_predicted=source == "adzuna" and random.random() < 0.5,
                url=f"https://www.example.com/jobs/{index}",
                posted_at=week - timedelta(days=random.randint(1, 30)),
            ))

    for _ in range(64):
        title, essential, desirable, salary = random.choice(ROLES)
        full = random.random() < 0.55
        source = "reed" if full else random.choice(["adzuna", "reed"])
        index += random.randint(1, 900)
        low = salary + random.choice([-4000, -2000, 0, 2000])
        postings.append(Posting(
            source=source,
            source_job_id=str(index),
            title=title,
            description=_description(title, essential, desirable, full),
            has_full_description=full,
            company=random.choice(COMPANIES),
            location=random.choice(LOCATIONS),
            salary_min=float(low),
            salary_max=float(low + random.choice([5000, 8000, 10000])),
            salary_is_predicted=source == "adzuna" and random.random() < 0.6,
            url=f"https://www.example.com/jobs/{index}",
            posted_at=week - timedelta(days=random.randint(1, 30)),
        ))

    for title, body in OUT_OF_DOMAIN:
        index += 7
        postings.append(Posting(
            source="reed", source_job_id=str(index), title=title,
            description=body + " " + ("Detail. " * 60), has_full_description=True,
            company=random.choice(COMPANIES), location="London",
            salary_min=40000.0, salary_max=50000.0,
            url=f"https://www.example.com/jobs/{index}",
            posted_at=week - timedelta(days=3),
        ))

    dashboard = build_dashboard(
        fetched=len(postings) + 21,
        duplicates=21,
        canonical=postings,
        requirements=[extract(p) for p in postings],
        profiles=Profile.load_all(Path("profiles")),
        skill_series={},
        week_of=week,
        generated_at=datetime(2026, 9, 21, 7, 4, tzinfo=UTC),
    )
    dashboard["is_sample"] = True

    out = Path("frontend/public/data/sample.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dashboard, indent=1), encoding="utf-8")
    print(f"Wrote {len(dashboard['roles'])} roles to {out}")


if __name__ == "__main__":
    main()
