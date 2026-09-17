"""Persistence for Agent 1.

Kept deliberately separate from the agent logic so the agent can be tested
without a database, which is why the ingestion tests run in CI with no
secrets and no service containers.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Iterator, Sequence

import psycopg
from psycopg.rows import dict_row

from agents.ingestion import Posting

logger = logging.getLogger(__name__)


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_schema(conn: psycopg.Connection, schema_path: str = "db/schema.sql") -> None:
    with open(schema_path, "r", encoding="utf-8") as handle:
        conn.execute(handle.read())


def start_run(conn: psycopg.Connection, source: str, query: str) -> int:
    row = conn.execute(
        "INSERT INTO ingestion_runs (source, query) VALUES (%s, %s) RETURNING id",
        (source, query),
    ).fetchone()
    return row["id"]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    fetched: int,
    inserted: int,
    duplicates: int,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE ingestion_runs
           SET finished_at = NOW(),
               fetched_count = %s,
               inserted_count = %s,
               duplicate_count = %s,
               status = %s,
               error_message = %s
         WHERE id = %s
        """,
        (fetched, inserted, duplicates, status, error_message, run_id),
    )


_UPSERT = """
INSERT INTO postings (
    source, source_job_id, title, company, location, category, contract_type,
    salary_min, salary_max, salary_currency, salary_is_predicted,
    description, has_full_description, url, posted_at, dedup_key, raw
) VALUES (
    %(source)s, %(source_job_id)s, %(title)s, %(company)s, %(location)s,
    %(category)s, %(contract_type)s, %(salary_min)s, %(salary_max)s,
    %(salary_currency)s, %(salary_is_predicted)s, %(description)s,
    %(has_full_description)s, %(url)s, %(posted_at)s, %(dedup_key)s, %(raw)s
)
ON CONFLICT (source, source_job_id) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    has_full_description = EXCLUDED.has_full_description,
    salary_min = EXCLUDED.salary_min,
    salary_max = EXCLUDED.salary_max,
    ingested_at = NOW()
RETURNING id
"""


def upsert_postings(conn: psycopg.Connection, postings: Sequence[Posting]) -> int:
    """Insert or refresh postings.

    Re-running ingestion for the same query must not create duplicate rows,
    so the unique constraint on (source, source_job_id) drives an upsert
    rather than a plain insert.
    """
    written = 0
    for posting in postings:
        row = posting.to_row()
        row["raw"] = json.dumps(row["raw"])
        conn.execute(_UPSERT, row)
        written += 1
    logger.info("Upserted %d postings", written)
    return written
