"""Skill families, used to award partial credit for adjacent experience.

The original design called for sentence transformer embeddings so that
"Airflow" would match "workflow orchestration". That turned out to be
unnecessary. Both the CV and the posting are normalised through the same
taxonomy before they are compared, so an exact match on canonical names already
handles synonyms. Embeddings would have added a 90MB model download, a slow
first run and a CI dependency, in exchange for nothing.

What embeddings would genuinely have offered is partial credit for related but
different skills. A candidate who knows PostgreSQL is not a perfect match for a
MySQL requirement, but they are far closer than someone who knows neither. That
relationship is captured here explicitly instead, which is deterministic,
testable and can be explained to a candidate in a sentence. An embedding
similarity of 0.73 cannot.
"""

from __future__ import annotations

# Skills within a family are substitutable to a degree. Membership is
# deliberately conservative: two skills belong together only if experience with
# one materially shortens the time to become productive with the other.
SKILL_FAMILIES: dict[str, list[str]] = {
    "relational_databases": ["PostgreSQL", "MySQL", "SQL"],
    "cloud_platforms": ["AWS", "Azure", "GCP"],
    "orchestration": ["Airflow", "Prefect", "Dagster", "Luigi", "Azure Data Factory"],
    "warehouses": ["Snowflake", "BigQuery", "Redshift", "Databricks", "Delta Lake"],
    "distributed_processing": ["Apache Spark", "PySpark", "Hadoop", "Flink"],
    "dataframes": ["pandas", "Polars", "NumPy"],
    "deep_learning": ["TensorFlow", "PyTorch", "Deep Learning"],
    "gradient_boosting": ["XGBoost", "LightGBM", "scikit-learn"],
    "bi_tools": ["Power BI", "Tableau", "Looker", "Qlik"],
    "containers": ["Docker", "Kubernetes"],
    "web_frameworks": ["FastAPI", "Flask", "Django"],
    "streaming": ["Kafka", "Flink"],
    "llm_stack": ["LLMs", "RAG", "Hugging Face", "NLP"],
    "iac": ["Terraform", "CI/CD"],
    "jvm_languages": ["Java", "Scala"],
}

# Credit awarded when a requirement is met by a family sibling rather than the
# skill itself. Tuned low deliberately: adjacent experience is worth
# acknowledging but should never look like the real thing.
FAMILY_CREDIT = 0.5


def skill_to_families() -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    for family, members in SKILL_FAMILIES.items():
        for member in members:
            lookup.setdefault(member, set()).add(family)
    return lookup


def are_related(left: str, right: str) -> bool:
    """True when two skills share at least one family."""
    lookup = skill_to_families()
    return bool(lookup.get(left, set()) & lookup.get(right, set()))
