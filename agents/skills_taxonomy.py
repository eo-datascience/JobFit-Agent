"""Curated skill taxonomy.

Skill detection is deliberately deterministic rather than model driven. Every
skill below is matched literally against the posting text, which means the
extraction agent cannot invent a requirement that is not present. The language
model is reserved for judgements that genuinely need one, such as seniority and
whether a requirement is essential, and even those are validated afterwards.

Named entity recognition was considered and rejected. General purpose NER models
are not trained on technical skill vocabulary, so they miss most of this list
while confidently tagging company names as skills. A curated taxonomy is smaller,
faster, fully testable and has no false positives by construction. Its weakness
is that it cannot find a skill it has never heard of, which is why the taxonomy
is a plain data structure that is cheap to extend.
"""

from __future__ import annotations

# canonical name -> aliases that should resolve to it.
# Aliases are matched case insensitively on word boundaries.
SKILL_TAXONOMY: dict[str, list[str]] = {
    # Languages
    "Python": ["python", "python3"],
    # Deliberately never a bare "r". A single letter matches "R&D", bullet
    # markers and initials, so only unambiguous forms are listed.
    "R": ["r programming", "rstats", "r language", "r studio", "rstudio", "r/python", "python/r"],
    "SQL": ["sql", "t-sql", "tsql", "pl/sql", "plsql", "ansi sql"],
    "Scala": ["scala"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js", "typescript", "ts"],
    # Same reasoning as R. "go" is far too common as an ordinary verb.
    "Go": ["golang", "go programming"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "csharp"],
    "Bash": ["bash", "shell scripting", "shell script"],

    # Data processing
    "PySpark": ["pyspark"],
    "Apache Spark": ["apache spark", "spark"],
    "pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Polars": ["polars"],
    "dbt": ["dbt", "data build tool"],
    "Hadoop": ["hadoop", "mapreduce"],
    "Kafka": ["kafka", "apache kafka"],
    "Flink": ["apache flink", "flink"],

    # Orchestration
    "Airflow": ["airflow", "apache airflow"],
    "Prefect": ["prefect"],
    "Dagster": ["dagster"],
    "Luigi": ["luigi"],
    "Azure Data Factory": ["azure data factory", "adf"],

    # Warehouses and databases
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery", "big query"],
    "Redshift": ["redshift"],
    "Databricks": ["databricks"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Cassandra": ["cassandra"],
    "Elasticsearch": ["elasticsearch", "elastic search"],
    "Delta Lake": ["delta lake"],

    # ML and analytics
    "scikit-learn": ["scikit-learn", "scikit learn", "sklearn"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch", "torch"],
    "XGBoost": ["xgboost"],
    "LightGBM": ["lightgbm"],
    "Hugging Face": ["hugging face", "huggingface", "transformers library"],
    "MLflow": ["mlflow"],
    "Machine Learning": ["machine learning", "ml models", "predictive modelling", "predictive modeling"],
    "Deep Learning": ["deep learning", "neural networks"],
    "NLP": ["nlp", "natural language processing", "text mining"],
    "Computer Vision": ["computer vision", "image recognition"],
    "Time Series": ["time series", "forecasting", "prophet", "arima"],
    "A/B Testing": ["a/b testing", "ab testing", "experimentation", "hypothesis testing"],
    "Statistics": ["statistics", "statistical analysis", "statistical modelling", "statistical modeling"],
    "LLMs": ["llm", "llms", "large language model", "large language models", "generative ai", "genai"],
    "RAG": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],

    # Cloud and infrastructure
    "AWS": ["aws", "amazon web services", "s3", "ec2", "lambda", "glue", "sagemaker"],
    "Azure": ["azure", "microsoft azure", "azure ml", "synapse"],
    "GCP": ["gcp", "google cloud", "google cloud platform", "vertex ai"],
    "Docker": ["docker", "containerisation", "containerization"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform", "infrastructure as code", "iac"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous deployment", "github actions", "jenkins"],
    "Linux": ["linux", "unix"],

    # BI and visualisation
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau"],
    "Looker": ["looker"],
    "Qlik": ["qlik", "qlikview", "qlik sense"],
    "Excel": ["excel", "advanced excel", "vba"],
    "Matplotlib": ["matplotlib", "seaborn", "plotly"],

    # Engineering practice
    "Git": ["git", "github", "gitlab", "version control"],
    "REST APIs": ["rest api", "rest apis", "restful", "api development"],
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "Django": ["django"],
    "Streamlit": ["streamlit"],
    "Testing": ["unit testing", "pytest", "test driven", "tdd"],
    "Agile": ["agile", "scrum", "kanban", "sprint"],

    # Data governance
    "Data Modelling": ["data modelling", "data modeling", "dimensional modelling", "star schema"],
    "Data Quality": ["data quality", "data validation", "great expectations"],
    "ETL": ["etl", "elt", "data pipeline", "data pipelines", "data ingestion"],
    "Data Governance": ["data governance", "gdpr", "data privacy", "data lineage"],
    "Data Warehousing": ["data warehouse", "data warehousing", "data lake", "lakehouse"],
}


# Seniority markers, ordered so that a more senior match wins when several appear.
SENIORITY_MARKERS: list[tuple[str, list[str]]] = [
    ("lead", ["head of", "principal", "lead ", "team lead", "tech lead", "director", "vp ", "chief"]),
    ("senior", ["senior", "snr", "sr.", "sr "]),
    ("mid", ["mid level", "mid-level", "intermediate"]),
    ("junior", ["junior", "jnr", "graduate", "entry level", "entry-level", "trainee",
                "apprentice", "intern", "placement", "no experience needed"]),
]


# Section headings that introduce a block of requirements. Skills found inside
# such a block inherit its status, which is far more reliable than looking for
# a cue near the skill itself.
ESSENTIAL_SECTION_HEADINGS: list[str] = [
    "essential", "requirements", "required", "must have", "what you need",
    "what we need", "what you'll need", "you will have", "you must have",
    "key skills", "skills and experience", "about you", "your experience",
    "minimum qualifications", "core skills",
]

DESIRABLE_SECTION_HEADINGS: list[str] = [
    "desirable", "nice to have", "nice-to-have", "preferred", "bonus",
    "advantageous", "would be a plus", "beneficial", "good to have",
    "additional skills", "ideally",
]


# Headings that end a requirements block. Without these, an "Essential:"
# section would run to the bottom of the posting and sweep up benefits,
# company blurb and application instructions, making every skill look
# mandatory and destroying the value of the essential signal.
NEUTRAL_SECTION_HEADINGS: list[str] = [
    "benefits", "what we offer", "what you'll get", "what you will get",
    "package", "salary", "rewards", "perks", "about us", "about the company",
    "who we are", "the company", "how to apply", "next steps",
    "application process", "interview process", "equal opportunities",
    "diversity", "inclusion", "the role", "role overview", "responsibilities",
    "the opportunity", "job description", "your responsibilities",
    "day to day", "what you'll be doing", "what you will be doing",
]


# Tokens in a job title that mark it as a data or engineering role. A posting
# with no taxonomy skill at all can still be in domain if its title says so,
# which covers genuinely vague postings that never name their tooling.
DOMAIN_TITLE_TOKENS: list[str] = [
    "data scientist", "data engineer", "data analyst", "data architect",
    "analytics engineer", "machine learning", "ml engineer", "mlops",
    "ai engineer", "research scientist", "quantitative", "statistician",
    "business intelligence", "bi developer", "bi analyst", "big data",
    "data platform", "data science", "analytics", "etl developer",
    "database", "data warehouse", "python developer", "backend engineer",
    "software engineer", "devops", "platform engineer",
]

# Title tokens that place a posting outside the field regardless of how many
# technology words its description happens to contain. A marketing role that
# mentions AI repeatedly is still a marketing role.
NON_DOMAIN_TITLE_TOKENS: list[str] = [
    "creative director", "art director", "copywriter", "designer",
    "marketing", "brand", "social media", "content creator", "recruiter",
    "recruitment consultant", "talent acquisition", "sales executive",
    "account manager", "business development", "customer success",
    "teacher", "tutor", "lecturer", "nurse", "care assistant",
    "paralegal", "solicitor", "accountant", "bookkeeper",
]


def canonical_skills() -> list[str]:
    return sorted(SKILL_TAXONOMY.keys())


def alias_to_canonical() -> dict[str, str]:
    """Flatten the taxonomy into an alias lookup.

    Longer aliases are returned first by the matcher so that "google cloud
    platform" is not shadowed by a shorter overlapping alias.
    """
    lookup: dict[str, str] = {}
    for canonical, aliases in SKILL_TAXONOMY.items():
        for alias in aliases:
            lookup[alias.lower()] = canonical
        # Only add the canonical name itself when it is long enough to be
        # unambiguous. "R" and "Go" would otherwise match ordinary prose.
        if len(canonical) > 2:
            lookup[canonical.lower()] = canonical
    return lookup
