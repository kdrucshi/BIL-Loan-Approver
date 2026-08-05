"""
SQLite schema, matching Evaluation_Engine.md section 10 exactly.

Hybrid model: compact rule_results (cheap to render) + append-only
audit_events (the "what happened" timeline). rule_results is keyed by
(loan_id, run_id) so runs are retained, not overwritten - the History screen
needs to compare past runs.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("../data/compliance.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS loans (
    loan_id            TEXT PRIMARY KEY,
    company_name       TEXT NOT NULL,
    hq_country         TEXT NOT NULL,
    asset_description  TEXT NOT NULL,
    asset_value        TEXT NOT NULL,   -- Decimal stored as text, 2dp
    asset_owner        TEXT NOT NULL,   -- kept on the loan row for display only; noise, no rule reads it
    loan_value         TEXT NOT NULL,   -- Decimal stored as text, 2dp
    loan_currency      TEXT NOT NULL,
    overall_status     TEXT NOT NULL DEFAULT 'pending'
        -- 'pending' | 'compliant' | 'has_failures' | 'removed' | 'resolved'
);

CREATE TABLE IF NOT EXISTS companies (
    company_name TEXT PRIMARY KEY,
    hq_country   TEXT NOT NULL,
    industry     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    company_name      TEXT NOT NULL,
    asset_description  TEXT NOT NULL,
    asset_value        TEXT NOT NULL,  -- Decimal as text
    PRIMARY KEY (company_name, asset_description),
    FOREIGN KEY (company_name) REFERENCES companies(company_name)
);

CREATE TABLE IF NOT EXISTS rule_results (
    loan_id           TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    rule1_pass        INTEGER NOT NULL,
    rule2_pass        INTEGER NOT NULL,
    rule3_pass        INTEGER NOT NULL,
    loan_value_eur    TEXT NOT NULL,   -- Decimal as text
    expected_currency TEXT NOT NULL,
    coverage_ratio    TEXT NOT NULL,   -- Decimal as text
    PRIMARY KEY (loan_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_rule_results_run ON rule_results(run_id);

CREATE TABLE IF NOT EXISTS suggestions (
    loan_id           TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    rule              INTEGER NOT NULL,       -- 1, 2, or 3
    suggestion_text   TEXT NOT NULL,          -- human-readable fix description
    suggested_value   TEXT,                   -- JSON blob: {"currency": "EUR"} or {"asset_description": ..., "asset_value": ...}
    confidence        REAL,                   -- only meaningful for rule 3 (retrieval-grounded); NULL for rule 1/2 (nothing uncertain) or a fallback pick
    reasoning         TEXT,                   -- agent's explanation, only for rule 3
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | manual | ignored
    via               TEXT,                   -- rule 3 only: 'llm' | 'fallback' (deterministic, LLM unavailable/unparsable)
    computed_at       TEXT,                   -- rule 3 only: when the background wave (or on-demand call) generated this
    PRIMARY KEY (loan_id, run_id, rule)
);
CREATE INDEX IF NOT EXISTS idx_suggestions_run ON suggestions(run_id);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL,
    ts        TEXT NOT NULL DEFAULT (datetime('now')),
    source    TEXT NOT NULL,   -- 'ingest' | 'evaluate' | 'rule_eval' | 'report' | 'reviewer'
    loan_id   TEXT,            -- nullable: run-level events have no loan_id
    rule_id   INTEGER,         -- nullable
    message   TEXT NOT NULL,
    meta      TEXT             -- JSON blob, nullable
);
CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_loan ON audit_events(loan_id);

CREATE TABLE IF NOT EXISTS run_meta (
    run_id                  TEXT PRIMARY KEY,
    status                  TEXT NOT NULL DEFAULT 'running',  -- running | completed | failed
    started_at              TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at            TEXT,
    total_loans             INTEGER NOT NULL DEFAULT 0,
    rule1_fails             INTEGER NOT NULL DEFAULT 0,
    rule2_fails             INTEGER NOT NULL DEFAULT 0,
    rule3_fails             INTEGER NOT NULL DEFAULT 0,
    removed                 INTEGER NOT NULL DEFAULT 0,
    fixed                   INTEGER NOT NULL DEFAULT 0,
    ignored                 INTEGER NOT NULL DEFAULT 0,
    unresolved              INTEGER NOT NULL DEFAULT 0,
    pre_review_compliance   REAL,
    post_review_compliance  REAL,
    fx_rate_date            TEXT,
    fx_source               TEXT,
    fx_stale                INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS never alters an already-existing table, so
    new columns added to SCHEMA after the db file was first created need an
    explicit, idempotent ALTER TABLE here - safe to run on every startup."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(suggestions)")}
    if "via" not in existing:
        conn.execute("ALTER TABLE suggestions ADD COLUMN via TEXT")
    if "computed_at" not in existing:
        conn.execute("ALTER TABLE suggestions ADD COLUMN computed_at TEXT")
    conn.commit()


def only_one_run_active(conn: sqlite3.Connection) -> bool:
    """Section 10: only one run may be `running` at a time."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM run_meta WHERE status = 'running'"
    ).fetchone()
    return row["n"] == 0
