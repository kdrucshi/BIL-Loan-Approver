"""
Engine 1 orchestrator: loans.csv -> compute inputs -> OPA (batches of 500) ->
SQLite (loans, rule_results, run_meta, audit_events).

Run with:  python -m pipeline.run_evaluation

Matches the processing flow in Evaluation_Engine.md section 4: stream the
CSV (never load all 100k into memory), one batch = 500 rows = 500 loans in
ONE OPA request, persist as we go.
"""

import csv
import json
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pipeline import db, opa_client
from pipeline.compute_inputs import HqCountryMismatch, compute_rule_inputs
from pipeline.fx import get_fx_rates
from pipeline.parse_pdf import build_and_cache, load_cached

LOANS_CSV = Path("../data/loans.csv")
COMPANIES_JSON = Path("../data/companies.json")
BATCH_SIZE = 500


def load_companies() -> dict:
    if not COMPANIES_JSON.exists():
        print("[evaluate] No cached companies.json - parsing PDF...")
        build_and_cache()
    return load_cached()


def _seed_reference_tables(conn, companies: dict) -> None:
    """Populate `companies` and `assets` from the parsed PDF, once per run.

    Companies/assets are reference data - upsert so re-running doesn't
    duplicate rows.
    """
    for name, c in companies.items():
        conn.execute(
            "INSERT OR REPLACE INTO companies (company_name, hq_country, industry) "
            "VALUES (?, ?, ?)",
            (name, c["hq_country"], c["industry"]),
        )
        for asset in c["assets"]:
            conn.execute(
                "INSERT OR REPLACE INTO assets (company_name, asset_description, asset_value) "
                "VALUES (?, ?, ?)",
                (name, asset["description"], str(Decimal(str(asset["value"])))),
            )
    conn.commit()


def _validate_row(row: dict) -> dict:
    """Coerce types, strip whitespace/line endings, trim join keys.

    Never alters business values (currencies, amounts) - section 4:
    "validate, don't clean." Raises on genuinely malformed rows rather than
    silently repairing them.
    """
    cleaned = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
    # Confirm the two monetary fields parse as Decimal - if they don't, this
    # row is malformed and should fail loudly, not be guessed at.
    Decimal(cleaned["loan_value"])
    Decimal(cleaned["asset_value"])
    return cleaned


def run() -> str:
    start = time.time()
    run_id = uuid.uuid4().hex[:12]

    conn = db.init_db()
    if not db.only_one_run_active(conn):
        raise RuntimeError("A run is already in progress; only one run at a time.")

    companies = load_companies()
    print(f"[evaluate] Loaded {len(companies)} companies from PDF cache.")
    _seed_reference_tables(conn, companies)

    # force_refresh=True: every explicit pipeline run fetches a live FX rate
    # rather than silently reusing an earlier run's same-day cache - a
    # reviewer clicking "Run pipeline" expects today's actual rate, not a
    # snapshot from hours ago (fx.py still falls back to the cache/stale
    # chain if the live fetch fails).
    fx = get_fx_rates(force_refresh=True)
    print(f"[evaluate] FX: source={fx.source} date={fx.rate_date} stale={fx.stale}")

    conn.execute(
        "INSERT INTO run_meta (run_id, status, fx_rate_date, fx_source, fx_stale) "
        "VALUES (?, 'running', ?, ?, ?)",
        (run_id, fx.rate_date, fx.source, int(fx.stale)),
    )
    conn.commit()
    _log_event(conn, run_id, "ingest", None, "Run started; loading loans.csv")

    total = 0
    rule1_fails = rule2_fails = rule3_fails = any_fail = 0
    compliant = 0
    mismatches = 0
    batch: list[dict] = []
    batch_inputs: list[dict] = []

    with LOANS_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            try:
                row = _validate_row(raw_row)
            except (InvalidOperation, KeyError) as exc:
                _log_event(
                    conn, run_id, "ingest", raw_row.get("loan_id"),
                    f"Malformed row skipped: {exc}",
                )
                continue

            inputs = compute_rule_inputs(row, companies, fx)
            if inputs["mismatch"] is not None:
                mismatches += 1
                m: HqCountryMismatch = inputs["mismatch"]
                _log_event(
                    conn, run_id, "ingest", row["loan_id"],
                    f"hq_country mismatch: CSV='{m.csv_country}' PDF='{m.pdf_country}' "
                    f"for company '{m.company_name}' - using PDF as authoritative",
                )

            batch.append((row, inputs))
            batch_inputs.append(inputs["opa_input"])
            total += 1

            if len(batch_inputs) >= BATCH_SIZE:
                r1, r2, r3, af, c = _flush_batch(conn, run_id, batch, batch_inputs)
                rule1_fails += r1
                rule2_fails += r2
                rule3_fails += r3
                any_fail += af
                compliant += c
                batch.clear()
                batch_inputs.clear()
                print(f"[evaluate] ...{total} loans processed")

    if batch_inputs:
        r1, r2, r3, af, c = _flush_batch(conn, run_id, batch, batch_inputs)
        rule1_fails += r1
        rule2_fails += r2
        rule3_fails += r3
        any_fail += af
        compliant += c

    pre_review_compliance = round(100.0 * compliant / total, 2) if total else 0.0

    conn.execute(
        """
        UPDATE run_meta SET
            status = 'completed',
            completed_at = datetime('now'),
            total_loans = ?,
            rule1_fails = ?,
            rule2_fails = ?,
            rule3_fails = ?,
            unresolved = ?,
            pre_review_compliance = ?
        WHERE run_id = ?
        """,
        (total, rule1_fails, rule2_fails, rule3_fails, any_fail, pre_review_compliance, run_id),
    )
    conn.commit()

    _log_event(conn, run_id, "evaluate", None, f"Rule 1: {rule1_fails} below EUR 25,000 after FX conversion")
    _log_event(conn, run_id, "evaluate", None, f"Rule 2: {rule2_fails} currency mismatches found")
    _log_event(conn, run_id, "evaluate", None, f"Rule 3: {rule3_fails} under-collateralised (asset < 50% of loan)")
    if mismatches:
        _log_event(conn, run_id, "evaluate", None, f"{mismatches} CSV/PDF hq_country disagreements flagged")
    _log_event(conn, run_id, "score", None, f"Pre-review compliance: {pre_review_compliance}%")
    conn.commit()

    # ---- FIX #1: Generate deterministic suggestions for Rule 1 and Rule 2 ----
    # Rule 1 ("remove from report") and Rule 2 ("change currency to X") are
    # deterministic — no LLM needed. Without these rows in the `suggestions`
    # table, the review UI and chatbot show "no suggestions" for R1/R2 loans.
    # Rule 3 suggestions are LLM-generated lazily (Wave 1/2) and stay as-is.
    _generate_deterministic_suggestions(conn, run_id)
    _log_event(conn, run_id, "evaluate", None, "Deterministic suggestions generated for Rule 1 and Rule 2 failures")
    conn.commit()

    conn.close()

    elapsed = time.time() - start
    print(f"\n[evaluate] Done: {total} loans in {elapsed:.1f}s | run_id={run_id}")
    print(
        f"[evaluate] rule1_fails={rule1_fails} rule2_fails={rule2_fails} "
        f"rule3_fails={rule3_fails} any_fail={any_fail} "
        f"pre_review_compliance={pre_review_compliance}%"
    )
    return run_id


def _generate_deterministic_suggestions(conn, run_id: str) -> None:
    """Insert suggestion records for all Rule 1 and Rule 2 failures.

    These are deterministic (values come from the static currency table and
    the EUR threshold, not from an LLM) so they can be batch-inserted right
    after evaluation, before any reviewer touches the data.

    Rule 3 suggestions require retrieval + LLM and are generated lazily
    by the agent (Action_Engine.md section 7, Wave 1/2).
    """
    # --- Rule 2: change currency to expected ---
    r2_rows = conn.execute(
        """
        SELECT rr.loan_id, rr.expected_currency, l.loan_currency,
               l.company_name, l.hq_country
        FROM rule_results rr
        JOIN loans l ON l.loan_id = rr.loan_id
        WHERE rr.run_id = ? AND rr.rule2_pass = 0
        """,
        (run_id,),
    ).fetchall()

    r2_suggestions = []
    for r in r2_rows:
        r2_suggestions.append((
            r["loan_id"],
            run_id,
            2,  # rule
            f"Change currency from {r['loan_currency']} to {r['expected_currency']}",
            json.dumps({"currency": r["expected_currency"]}),
            None,  # confidence: not applicable for deterministic fixes
            f"{r['company_name']} is headquartered in {r['hq_country']}; "
            f"expected currency is {r['expected_currency']} but loan is "
            f"reported in {r['loan_currency']}.",
            "pending",
        ))

    if r2_suggestions:
        conn.executemany(
            """
            INSERT OR IGNORE INTO suggestions
                (loan_id, run_id, rule, suggestion_text, suggested_value,
                 confidence, reasoning, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            r2_suggestions,
        )
    print(f"[evaluate] Generated {len(r2_suggestions)} Rule 2 suggestions")

    # --- Rule 1: remove from report ---
    r1_rows = conn.execute(
        """
        SELECT rr.loan_id, rr.loan_value_eur
        FROM rule_results rr
        WHERE rr.run_id = ? AND rr.rule1_pass = 0
        """,
        (run_id,),
    ).fetchall()

    r1_suggestions = []
    for r in r1_rows:
        r1_suggestions.append((
            r["loan_id"],
            run_id,
            1,  # rule
            "Remove from report (below EUR 25,000 threshold)",
            None,  # suggested_value: no correctable value for Rule 1
            None,  # confidence: deterministic
            f"Loan value in EUR is {r['loan_value_eur']}, which is not strictly "
            f"more than EUR 25,000.00. This loan is out of scope for reporting.",
            "pending",
        ))

    if r1_suggestions:
        conn.executemany(
            """
            INSERT OR IGNORE INTO suggestions
                (loan_id, run_id, rule, suggestion_text, suggested_value,
                 confidence, reasoning, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            r1_suggestions,
        )
    print(f"[evaluate] Generated {len(r1_suggestions)} Rule 1 suggestions")

    conn.commit()


def _flush_batch(conn, run_id: str, batch: list[tuple[dict, dict]], batch_inputs: list[dict]):
    verdicts = opa_client.evaluate_batch(batch_inputs)

    r1_fails = r2_fails = r3_fails = any_fail = compliant = 0
    loan_rows = []
    result_rows = []

    for row, inputs in batch:
        loan_id = row["loan_id"]
        v = verdicts[loan_id]  # keyed by loan_id, never by array order
        rule1_pass = v["rule1"]["pass"]
        rule2_pass = v["rule2"]["pass"]
        rule3_pass = v["rule3"]["pass"]

        if not rule1_pass:
            r1_fails += 1
        if not rule2_pass:
            r2_fails += 1
        if not rule3_pass:
            r3_fails += 1
        if rule1_pass and rule2_pass and rule3_pass:
            compliant += 1
        else:
            any_fail += 1

        overall_status = "compliant" if (rule1_pass and rule2_pass and rule3_pass) else "has_failures"

        loan_rows.append(
            (
                loan_id, row["company_name"], row["hq_country"], row["asset_description"],
                str(Decimal(row["asset_value"])), row["asset_owner"],
                str(Decimal(row["loan_value"])), row["loan_currency"], overall_status,
            )
        )
        result_rows.append(
            (
                loan_id, run_id, int(rule1_pass), int(rule2_pass), int(rule3_pass),
                str(inputs["loan_value_eur"]), inputs["expected_currency"],
                str(v["rule3"]["coverage_ratio"]),
            )
        )

    conn.executemany(
        """
        INSERT OR REPLACE INTO loans (
            loan_id, company_name, hq_country, asset_description, asset_value,
            asset_owner, loan_value, loan_currency, overall_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        loan_rows,
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO rule_results (
            loan_id, run_id, rule1_pass, rule2_pass, rule3_pass,
            loan_value_eur, expected_currency, coverage_ratio
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        result_rows,
    )
    conn.commit()

    return r1_fails, r2_fails, r3_fails, any_fail, compliant


def _log_event(conn, run_id: str, source: str, loan_id: str | None, message: str, meta: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_events (run_id, source, loan_id, message, meta) VALUES (?, ?, ?, ?, ?)",
        (run_id, source, loan_id, message, json.dumps(meta) if meta else None),
    )


if __name__ == "__main__":
    run()