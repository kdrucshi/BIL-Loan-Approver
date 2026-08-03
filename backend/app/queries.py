"""
All read queries for the FastAPI app, kept separate from route handling so
the SQL is easy to find, read, and unit-test independently of HTTP concerns.
"""

import json
from decimal import Decimal

from pipeline.db import get_connection


def latest_completed_run_id(conn) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM run_meta WHERE status = 'completed' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row["run_id"] if row else None


def run_summary(conn, run_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    summary = dict(row)
    summary["post_review_compliance"] = post_review_compliance(conn, run_id, summary["total_loans"])
    # run_meta.removed is a static count stamped at evaluation time (always 0 -
    # nothing is removed until a reviewer decides). Recompute live from loans
    # so the dashboard's "Removed" stat reflects reviewer actions as they land.
    summary["removed"] = _removed_count(conn)
    return summary


def _removed_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM loans WHERE overall_status = 'removed'"
    ).fetchone()["n"]


def post_review_compliance(conn, run_id: str, total_loans: int) -> float | None:
    """Evaluation_Engine.md section 10: compliant = passed originally OR was
    fixed. Rule 1 removals LEAVE THE DENOMINATOR - a removed loan is out of
    scope, not non-compliant. Computed fresh from current loan state rather
    than stored, so it's always accurate as reviewer actions land."""
    removed = _removed_count(conn)
    compliant = conn.execute(
        "SELECT COUNT(*) AS n FROM loans WHERE overall_status = 'compliant'"
    ).fetchone()["n"]
    denom = total_loans - removed
    if denom <= 0:
        return None
    return round(100 * compliant / denom, 2)


def list_runs(conn, limit: int = 20) -> list[dict]:
    """Recomputes post_review_compliance per run (run_meta's stored column is
    never updated after evaluation) so History / Recent-runs reflect reviewer
    progress instead of always falling back to the pre-review score."""
    rows = conn.execute(
        "SELECT * FROM run_meta ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    runs = [dict(r) for r in rows]
    for r in runs:
        r["post_review_compliance"] = post_review_compliance(conn, r["run_id"], r["total_loans"])
    return runs


def score_trend(conn, limit: int = 7) -> list[dict]:
    rows = conn.execute(
        """
        SELECT run_id, started_at, pre_review_compliance, post_review_compliance
        FROM run_meta WHERE status = 'completed'
        ORDER BY started_at ASC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def rule_breakdown(conn, run_id: str) -> list[dict]:
    row = conn.execute(
        "SELECT total_loans, rule1_fails, rule2_fails, rule3_fails FROM run_meta WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return []
    total = row["total_loans"]
    defs = [
        (1, "Minimum loan value", "> EUR 25,000 (EUR)", row["rule1_fails"]),
        (2, "Currency matches HQ", "currency == country", row["rule2_fails"]),
        (3, "Asset coverage", "asset >= 50% of loan", row["rule3_fails"]),
    ]
    return [
        {
            "rule": r,
            "name": name,
            "condition": cond,
            "passed": total - fails,
            "failed": fails,
            "fail_pct": round(100 * fails / total, 2) if total else 0.0,
        }
        for r, name, cond, fails in defs
    ]


def portfolio_by_company(conn, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT company_name, hq_country, COUNT(*) AS n_loans,
               SUM(CAST(loan_value AS REAL)) AS total_value, loan_currency
        FROM loans
        GROUP BY company_name
        ORDER BY total_value DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def fx_fragility(conn, run_id: str, band_pct: float = 5.0) -> dict:
    """Signal 1 from Insights-FX.md: non-EUR loans within `band_pct`% of the
    EUR 25,000 Rule 1 threshold, split into fragile-passes and near-miss
    removals. Pure arithmetic over rule_results.loan_value_eur - no model."""
    rows = conn.execute(
        """
        SELECT l.loan_id, l.company_name, l.loan_currency, rr.loan_value_eur
        FROM rule_results rr
        JOIN loans l ON l.loan_id = rr.loan_id
        WHERE rr.run_id = ? AND l.loan_currency != 'EUR'
        """,
        (run_id,),
    ).fetchall()

    floor = Decimal("25000")
    band = Decimal(str(band_pct)) / Decimal("100")
    above, below = [], []

    for r in rows:
        eur = Decimal(r["loan_value_eur"])
        distance_pct = (eur - floor) / floor
        if abs(distance_pct) <= band:
            entry = {
                "loan_id": r["loan_id"],
                "company_name": r["company_name"],
                "currency": r["loan_currency"],
                "eur_value": float(eur),
                "distance_pct": float(distance_pct * 100),
            }
            (above if distance_pct > 0 else below).append(entry)

    above.sort(key=lambda x: x["distance_pct"])
    below.sort(key=lambda x: -x["distance_pct"])

    return {
        "band_pct": band_pct,
        "floor_eur": float(floor),
        "total_above": len(above),
        "total_below": len(below),
        "above": above,
        "below": below,
    }


def review_groups(conn, run_id: str) -> list[dict]:
    """Deterministic grouping by fix-signature (Action_Engine.md section 8).
    AI-generated per-group narrative summaries are added by Engine 2 - this
    endpoint returns the deterministic group shape and counts only, with
    `summary: null` until the agent fills it in.
    """
    groups: list[dict] = []

    # Precedence-aware (Action_Engine.md §6): a loan failing several rules
    # counts only in its highest-precedence bucket (Rule 2 -> Rule 1 -> Rule 3),
    # matching _BUCKET_WHERE below exactly so these counts equal what
    # /api/review/loans?bucket=N actually returns.
    rule1_row = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM rule_results rr
        WHERE rr.run_id = ? AND {_BUCKET_WHERE[1]}
        """,
        (run_id,),
    ).fetchone()
    if rule1_row["n"]:
        groups.append(
            {
                "id": "rule1-remove",
                "rule": 1,
                "title": "Below EUR 25,000 after conversion",
                "fix": "Remove from report (out of scope)",
                "count": rule1_row["n"],
                "summary": None,
            }
        )

    rule2_rows = conn.execute(
        f"""
        SELECT rr.expected_currency, COUNT(*) AS n
        FROM rule_results rr
        WHERE rr.run_id = ? AND {_BUCKET_WHERE[2]}
        GROUP BY rr.expected_currency
        ORDER BY n DESC
        """,
        (run_id,),
    ).fetchall()
    for r in rule2_rows:
        groups.append(
            {
                "id": f"rule2-to-{r['expected_currency']}",
                "rule": 2,
                "title": f"Loans that should be reported in {r['expected_currency']}",
                "fix": f"Change currency to {r['expected_currency']}",
                "count": r["n"],
                "summary": None,
            }
        )

    rule3_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM rule_results rr WHERE rr.run_id = ? AND {_BUCKET_WHERE[3]}",
        (run_id,),
    ).fetchone()
    if rule3_row["n"]:
        groups.append(
            {
                "id": "rule3-coverage",
                "rule": 3,
                "title": "Insufficient collateral - asset < 50% of loan",
                "fix": "Substitute a qualifying asset (per loan - see Action_Engine.md \u00a78)",
                "count": rule3_row["n"],
                "summary": None,
            }
        )

    return groups


def audit_trail(conn, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, source, loan_id, message, meta FROM audit_events "
        "WHERE run_id = ? ORDER BY event_id ASC",
        (run_id,),
    ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        entry["meta"] = json.loads(entry["meta"]) if entry["meta"] else None
        result.append(entry)
    return result


# Single-bucket precedence model (Action_Engine.md section 6): Rule 2 -> Rule
# 1 -> Rule 3. Every failing loan is shown in exactly ONE bucket at a time.
_BUCKET_WHERE = {
    2: "rr.rule2_pass = 0",
    1: "rr.rule2_pass = 1 AND rr.rule1_pass = 0",
    3: "rr.rule2_pass = 1 AND rr.rule1_pass = 1 AND rr.rule3_pass = 0",
}


def bucket_loans(conn, run_id: str, bucket: int, limit: int = 50, offset: int = 0) -> dict:
    """Paginated (never loads all rows at once - required at 100k scale)."""
    where = _BUCKET_WHERE[bucket]
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM rule_results rr WHERE rr.run_id = ? AND {where}",
        (run_id,),
    ).fetchone()["n"]

    rows = conn.execute(
        f"""
        SELECT l.loan_id, l.company_name, l.hq_country, l.loan_value, l.loan_currency,
               l.asset_description, l.asset_value, l.overall_status,
               rr.loan_value_eur, rr.expected_currency, rr.coverage_ratio,
               s.suggestion_text, s.reasoning, s.status AS suggestion_status
        FROM rule_results rr
        JOIN loans l ON l.loan_id = rr.loan_id
        LEFT JOIN suggestions s ON s.loan_id = rr.loan_id AND s.run_id = rr.run_id AND s.rule = ?
        WHERE rr.run_id = ? AND {where}
        ORDER BY l.loan_id
        LIMIT ? OFFSET ?
        """,
        (bucket, run_id, limit, offset),
    ).fetchall()

    return {"total": total, "limit": limit, "offset": offset, "loans": [dict(r) for r in rows]}

