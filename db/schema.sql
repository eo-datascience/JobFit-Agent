-- JobFit Agent: core schema
-- Phase 1 covers postings and ingestion_runs. Later phases add
-- extracted_requirements, fit_scores, skill_counts and application_outcomes.

CREATE TABLE IF NOT EXISTS postings (
    id                  BIGSERIAL PRIMARY KEY,

    -- Provenance
    source              TEXT        NOT NULL CHECK (source IN ('adzuna', 'reed')),
    source_job_id       TEXT        NOT NULL,

    -- Core fields, normalised across both providers
    title               TEXT        NOT NULL,
    company             TEXT,
    location            TEXT,
    category            TEXT,
    contract_type       TEXT,

    -- Salary. salary_is_predicted flags Adzuna's modelled figures so that
    -- downstream scoring can weight a stated range above an inferred one.
    salary_min          NUMERIC(12, 2),
    salary_max          NUMERIC(12, 2),
    salary_currency     TEXT        DEFAULT 'GBP',
    salary_is_predicted BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Description. has_full_description is false for Adzuna excerpts, which
    -- the extraction agent uses to decide whether a posting is worth parsing.
    description         TEXT        NOT NULL,
    has_full_description BOOLEAN    NOT NULL DEFAULT FALSE,

    url                 TEXT,
    posted_at           DATE,

    -- Deduplication
    dedup_key           TEXT        NOT NULL,
    is_duplicate_of     BIGINT      REFERENCES postings (id) ON DELETE SET NULL,

    raw                 JSONB       NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT postings_source_job_unique UNIQUE (source, source_job_id)
);

CREATE INDEX IF NOT EXISTS postings_dedup_key_idx   ON postings (dedup_key);
CREATE INDEX IF NOT EXISTS postings_ingested_at_idx ON postings (ingested_at DESC);
CREATE INDEX IF NOT EXISTS postings_canonical_idx   ON postings (id) WHERE is_duplicate_of IS NULL;

-- One row per ingestion run, so a failed or thin run is visible in the data
-- rather than only in the logs.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                BIGSERIAL PRIMARY KEY,
    source            TEXT        NOT NULL,
    query             TEXT        NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at       TIMESTAMPTZ,
    fetched_count     INTEGER     NOT NULL DEFAULT 0,
    inserted_count    INTEGER     NOT NULL DEFAULT 0,
    duplicate_count   INTEGER     NOT NULL DEFAULT 0,
    status            TEXT        NOT NULL DEFAULT 'running'
                                  CHECK (status IN ('running', 'success', 'failed')),
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS ingestion_runs_started_idx ON ingestion_runs (started_at DESC);
