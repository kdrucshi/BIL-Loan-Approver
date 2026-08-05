"""
All read queries for the FastAPI app, kept separate from route handling so
the SQL is easy to find, read, and unit-test independently of HTTP concerns.
"""

import json
from decimal import Decimal

from pipeline.db import get_connection
from pipeline.fx import get_fx_rates
from pipeline.parse_pdf import load_cached, load_pdf_total_pages


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


def any_fail_count(conn, run_id: str) -> int:
    """Loans currently failing at least one rule, per this run's rule_results
    (live, not the static per-rule counts stamped at evaluation time). Single
    source of truth shared by /api/dashboard and the page assistant, so the
    two never drift apart."""
    return conn.execute(
        "SELECT COUNT(*) AS n FROM rule_results WHERE run_id = ? "
        "AND NOT (rule1_pass = 1 AND rule2_pass = 1 AND rule3_pass = 1)",
        (run_id,),
    ).fetchone()["n"]


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


# ---- FIX #4: rule_breakdown now includes EUR exposure per rule ----

def rule_breakdown(conn, run_id: str) -> list[dict]:
    row = conn.execute(
        "SELECT total_loans, rule1_fails, rule2_fails, rule3_fails FROM run_meta WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return []
    total = row["total_loans"]

    # EUR exposure per rule (SUM of loan_value_eur for loans failing that rule)
    eur_exposure = {}
    for rule in (1, 2, 3):
        eur_row = conn.execute(
            f"SELECT SUM(CAST(loan_value_eur AS REAL)) AS eur FROM rule_results "
            f"WHERE run_id = ? AND rule{rule}_pass = 0",
            (run_id,),
        ).fetchone()
        eur_exposure[rule] = eur_row["eur"] or 0.0

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
            "eur_exposure": eur_exposure[r],
        }
        for r, name, cond, fails in defs
    ]


# ---- FIX #2: portfolio_by_company now uses EUR-normalized values ----
# Old version summed raw loan_value across mixed currencies (GBP, JPY, EUR
# etc.) making the sort order meaningless. Now joins rule_results to use
# loan_value_eur, matching what reports.py._portfolio_eur already does.
# Also adds a failure count per company and requires run_id.

def portfolio_by_company(conn, run_id: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.company_name, l.hq_country, COUNT(*) AS n_loans,
               SUM(CAST(rr.loan_value_eur AS REAL)) AS total_eur,
               SUM(CASE WHEN NOT (rr.rule1_pass = 1 AND rr.rule2_pass = 1 AND rr.rule3_pass = 1)
                   THEN 1 ELSE 0 END) AS failures
        FROM loans l
        JOIN rule_results rr ON rr.loan_id = l.loan_id AND rr.run_id = ?
        GROUP BY l.company_name, l.hq_country
        ORDER BY total_eur DESC
        LIMIT ?
        """,
        (run_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fx_fragility(conn, run_id: str, band_pct: float = 0.5) -> dict:
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


def _loans_filter_sql(
    ccy: str | None, min_value: float | None, max_value: float | None, low_conf: bool,
    q: str | None = None,
) -> tuple[str, list]:
    """Shared WHERE-fragment + params for filtering the review queue AND for
    bulk-decide's 'select all matching' - these two MUST stay in lockstep so
    a bulk action never covers more or fewer loans than the reviewer
    currently sees (Review screen integration guide, section 6)."""
    clauses = []
    params: list = []
    if ccy:
        clauses.append("l.loan_currency = ?")
        params.append(ccy)
    if min_value is not None:
        clauses.append("CAST(rr.loan_value_eur AS REAL) >= ?")
        params.append(min_value)
    if max_value is not None:
        clauses.append("CAST(rr.loan_value_eur AS REAL) <= ?")
        params.append(max_value)
    if low_conf:
        clauses.append("s.confidence IS NOT NULL AND s.confidence < 80")
    if q:
        clauses.append("(l.loan_id LIKE ? OR l.company_name LIKE ?)")
        needle = f"%{q}%"
        params.extend([needle, needle])
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def bucket_loans(
    conn, run_id: str, bucket: int, limit: int = 50, offset: int = 0,
    ccy: str | None = None, min_value: float | None = None, max_value: float | None = None,
    low_conf: bool = False, sort: str = "value_desc", q: str | None = None,
) -> dict:
    """Paginated (never loads all rows at once - required at 100k scale).

    Optional filters run as real SQL WHERE clauses, and `filtered_total` is a
    genuine COUNT(*) of the SAME filtered query - the fix for a pager that
    otherwise reflects the whole stage instead of the filtered set.
    """
    where = _BUCKET_WHERE[bucket]
    filter_sql, filter_params = _loans_filter_sql(ccy, min_value, max_value, low_conf, q)

    order_by = {
        "value_desc": "CAST(l.loan_value AS REAL) DESC",
        "value_asc": "CAST(l.loan_value AS REAL) ASC",
        "conf_desc": "s.confidence DESC",
        "conf_asc": "s.confidence ASC",
    }.get(sort, "CAST(l.loan_value AS REAL) DESC")

    base_from = f"""
        FROM rule_results rr
        JOIN loans l ON l.loan_id = rr.loan_id
        LEFT JOIN suggestions s ON s.loan_id = rr.loan_id AND s.run_id = rr.run_id AND s.rule = ?
        WHERE rr.run_id = ? AND l.overall_status = 'has_failures' AND {where}{filter_sql}
    """
    count_params = [bucket, run_id, *filter_params]
    filtered_total = conn.execute(f"SELECT COUNT(*) AS n {base_from}", count_params).fetchone()["n"]
    # Unfiltered stage total, so the frontend can show "N match / of TOTAL in this stage".
    total = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM rule_results rr
        JOIN loans l ON l.loan_id = rr.loan_id
        WHERE rr.run_id = ? AND l.overall_status = 'has_failures' AND {where}
        """,
        (run_id,),
    ).fetchone()["n"]

    rows = conn.execute(
        f"""
        SELECT l.loan_id, l.company_name, l.hq_country, l.loan_value, l.loan_currency,
               l.asset_description, l.asset_value, l.overall_status,
               rr.loan_value_eur, rr.expected_currency, rr.coverage_ratio,
               rr.rule1_pass, rr.rule2_pass, rr.rule3_pass,
               s.suggestion_text, s.reasoning, s.status AS suggestion_status, s.confidence
        {base_from}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        [*count_params, limit, offset],
    ).fetchall()

    return {
        "total": total,
        "filtered_total": filtered_total,
        "limit": limit,
        "offset": offset,
        "loans": [dict(r) for r in rows],
    }


def pending_by_rule(conn, run_id: str) -> dict:
    """Loans currently open in each Review-queue bucket, precedence-aware
    (Action_Engine.md section 6) - reuses the SAME _BUCKET_WHERE clauses
    bucket_loans()/review_groups() use, so this always matches what the
    Review tab shows, never a separately-drifting count."""
    counts = {
        rule: conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM rule_results rr
            JOIN loans l ON l.loan_id = rr.loan_id
            WHERE rr.run_id = ? AND l.overall_status = 'has_failures' AND {where}
            """,
            (run_id,),
        ).fetchone()["n"]
        for rule, where in _BUCKET_WHERE.items()
    }
    counts["total"] = sum(counts.values())
    return counts


# The 3 fixed review stages, in precedence order R2 -> R1 -> R3
# (n = display order, rule = the OPA rule number that stage reviews).
_STAGE_DEFS = [(1, 2, "Currency Validation"), (2, 1, "Loan Eligibility"), (3, 3, "Collateral Review")]


def review_stages(conn, run_id: str) -> list[dict]:
    """The 3 fixed review stages, each with the count of loans CURRENTLY in
    that bucket. `state` is a UI hint only (which stage the reviewer happens
    to be looking at) - it never gates anything; a loan only ever failing
    Rule 3 is reviewable immediately regardless of how many Rule 2 loans are
    still open (Action_Engine.md section 6)."""
    counts = pending_by_rule(conn, run_id)
    stages = [
        {"n": n, "rule": rule, "name": name, "queue": counts.get(rule, 0)}
        for n, rule, name in _STAGE_DEFS
    ]
    active_n = next((s["n"] for s in stages if s["queue"] > 0), stages[0]["n"])
    for s in stages:
        s["state"] = "active" if s["n"] == active_n else "pending"
    return stages


def review_summary(conn, run_id: str, rule: int) -> dict:
    """Headline counts for one stage's queue plus overall run-wide progress.

    'ignored' is a best-effort count from audit_events (any loan ever logged
    as 'ignored' for this rule in this run) - a simple, defensible headline
    stat rather than reconstructing full per-loan decision history.
    'overall.reviewed' counts loans that are compliant, removed, or ignored
    (at least once, any rule) - a terminal outcome, not just "currently
    passing" (which would undercount ignored-but-still-failing loans).
    """
    where = _BUCKET_WHERE[rule]
    needs_review = conn.execute(
        f"SELECT COUNT(*) AS n FROM rule_results rr WHERE rr.run_id = ? AND {where}",
        (run_id,),
    ).fetchone()["n"]

    suggested = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM rule_results rr
        JOIN suggestions s ON s.loan_id = rr.loan_id AND s.run_id = rr.run_id AND s.rule = ?
        WHERE rr.run_id = ? AND {where} AND s.status = 'pending'
        """,
        (rule, run_id),
    ).fetchone()["n"]

    ignored = conn.execute(
        """
        SELECT COUNT(DISTINCT loan_id) AS n FROM audit_events
        WHERE run_id = ? AND source = 'reviewer' AND message = 'ignored'
          AND json_extract(meta, '$.rule') = ?
        """,
        (run_id, rule),
    ).fetchone()["n"]

    total_row = conn.execute("SELECT total_loans FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    total = total_row["total_loans"] if total_row else 0
    compliant_or_removed = conn.execute(
        "SELECT COUNT(*) AS n FROM loans WHERE overall_status IN ('compliant', 'removed')"
    ).fetchone()["n"]
    ignored_any_rule = conn.execute(
        "SELECT COUNT(DISTINCT loan_id) AS n FROM audit_events "
        "WHERE run_id = ? AND source = 'reviewer' AND message = 'ignored'",
        (run_id,),
    ).fetchone()["n"]

    return {
        "stage": rule,
        "queue": {"suggested": suggested, "needsReview": needs_review, "ignored": ignored},
        "overall": {"reviewed": compliant_or_removed + ignored_any_rule, "total": total},
    }


def loan_review_detail(conn, run_id: str, loan_id: str) -> dict | None:
    """Everything the Review journey screen's Detail/Impact/evidence panels
    need for ONE loan: its active (highest-precedence) bucket, the fix it
    needs, PDF evidence backing Rule 2 (from the parsed companies cache, real
    extracted text only - never an invented sentence), and the Rule 1 FX
    conversion math when Rule 1 is in play. Returns None if the loan or its
    rule_results row for this run doesn't exist.
    """
    loan = conn.execute(
        """
        SELECT l.*, c.industry AS company_industry
        FROM loans l LEFT JOIN companies c ON c.company_name = l.company_name
        WHERE l.loan_id = ?
        """,
        (loan_id,),
    ).fetchone()
    if loan is None:
        return None

    rr = conn.execute(
        "SELECT rule1_pass, rule2_pass, rule3_pass, loan_value_eur, expected_currency, coverage_ratio "
        "FROM rule_results WHERE run_id = ? AND loan_id = ?",
        (run_id, loan_id),
    ).fetchone()
    if rr is None:
        return None

    if not rr["rule2_pass"]:
        active = 2
    elif not rr["rule1_pass"]:
        active = 1
    elif not rr["rule3_pass"]:
        active = 3
    else:
        active = None
    also_fails = [
        r for r, passed in ((1, rr["rule1_pass"]), (2, rr["rule2_pass"]), (3, rr["rule3_pass"]))
        if r != active and not passed
    ]

    suggestion = None
    if active is not None:
        suggestion = conn.execute(
            "SELECT rule, suggestion_text, suggested_value, confidence, reasoning, status, via, computed_at "
            "FROM suggestions WHERE run_id = ? AND loan_id = ? AND rule = ?",
            (run_id, loan_id, active),
        ).fetchone()

    if active == 2:
        fix = {"type": "currency", "from": loan["loan_currency"], "to": rr["expected_currency"]}
    elif active == 1:
        fix = {"type": "remove"}
    elif active == 3:
        if suggestion and suggestion["suggested_value"]:
            fix = {"type": "substitute_asset", **json.loads(suggestion["suggested_value"])}
        else:
            fix = {"type": "none"}
    else:
        fix = {"type": "none"}

    evidence = None
    if active == 2 or 2 in also_fails:
        companies = load_cached()
        company = companies.get(loan["company_name"])
        if company is not None:
            hq_evidence = company.get("hq_evidence") or {}
            evidence = {
                "pdfPage": company.get("pdf_page"),
                "pdfTotal": load_pdf_total_pages(),
                "snippet": hq_evidence.get("snippet"),
                "highlight": hq_evidence.get("highlight"),
            }

    r3_assets = None
    if active == 3:
        loan_value_dec = Decimal(loan["loan_value"])
        threshold = loan_value_dec * Decimal("0.5")
        # All of a company's pledgeable assets are listed on its ONE profile
        # page in company-reference.pdf (parse_pdf.py) - there's no separate
        # per-asset page, so every asset here honestly shares the company's
        # single pdf_page. There is no parsed per-asset type/location/owner
        # field (parse_pdf.py explicitly drops "Related entities" as noise
        # no rule reads), so no fabricated "detail" line is added here.
        companies = load_cached()
        company = companies.get(loan["company_name"])
        company_pdf_page = company.get("pdf_page") if company else None
        asset_rows = conn.execute(
            "SELECT asset_description, asset_value FROM assets WHERE company_name = ? ORDER BY asset_description",
            (loan["company_name"],),
        ).fetchall()
        r3_assets = [
            {
                "name": a["asset_description"],
                "value": float(Decimal(a["asset_value"])),
                "qualifies": Decimal(a["asset_value"]) >= threshold,
                "coverage": float(Decimal(a["asset_value"]) / loan_value_dec) if loan_value_dec else 0.0,
                "current": a["asset_description"] == loan["asset_description"],
                "pdfPage": company_pdf_page,
            }
            for a in asset_rows
        ]

    impact = {"recheck": "all"}
    if active == 1 or 1 in also_fails:
        fx = get_fx_rates()  # default: reuses this run's already-cached rates, no live call
        rate = fx.rates.get(loan["loan_currency"])
        impact["fx"] = {
            "currency": loan["loan_currency"],
            "rate_to_eur": float(1 / rate) if rate else None,
            "converted_eur": float(Decimal(rr["loan_value_eur"])),
            "source": fx.source,
            "as_of": fx.rate_date,
            "stale": fx.stale,
        }

    loan_value = Decimal(loan["loan_value"])
    return {
        "id": loan["loan_id"],
        "co": loan["company_name"],
        "hq": loan["hq_country"],
        "industry": loan["company_industry"],
        "ccy": loan["loan_currency"],
        "value": f"{loan_value:,.2f}",
        "valueNum": float(loan_value),
        "confidence": suggestion["confidence"] if suggestion else None,
        "reasoning": suggestion["reasoning"] if suggestion else None,
        "rule_failed": active,
        "also_fails": also_fails,
        "fix": fix,
        "assets": r3_assets,
        "via": suggestion["via"] if suggestion else None,
        "computed": bool(suggestion["computed_at"]) if suggestion else False,
        "evidence": evidence,
        "impact": impact,
    }


def loan_detail(conn, run_id: str, loan_id: str) -> dict | None:
    """Full grounded detail for ONE loan - its data, this run's rule
    verdicts, any suggestion generated for it, and its audit history. This is
    what lets the page assistant honestly answer "why did loan X fail?"
    without inventing anything not already in the database. Returns None if
    the loan doesn't exist at all."""
    loan = conn.execute("SELECT * FROM loans WHERE loan_id = ?", (loan_id,)).fetchone()
    if loan is None:
        return None

    rr = conn.execute(
        "SELECT rule1_pass, rule2_pass, rule3_pass, loan_value_eur, expected_currency, coverage_ratio "
        "FROM rule_results WHERE run_id = ? AND loan_id = ?",
        (run_id, loan_id),
    ).fetchone()

    suggestions = conn.execute(
        "SELECT rule, suggestion_text, reasoning, status FROM suggestions "
        "WHERE run_id = ? AND loan_id = ?",
        (run_id, loan_id),
    ).fetchall()

    events = conn.execute(
        "SELECT ts, source, message, meta FROM audit_events WHERE loan_id = ? ORDER BY event_id ASC",
        (loan_id,),
    ).fetchall()

    rule_results_dict = dict(rr) if rr else None
    if rule_results_dict:
        rule_results_dict["rule1_verdict"] = "FAIL" if not rr["rule1_pass"] else "PASS"
        rule_results_dict["rule2_verdict"] = "FAIL" if not rr["rule2_pass"] else "PASS"
        rule_results_dict["rule3_verdict"] = "FAIL" if not rr["rule3_pass"] else "PASS"

    return {
        "loan": dict(loan),
        "rule_results_this_run": rule_results_dict,
        "suggestions": [dict(s) for s in suggestions],
        "audit_events": [
            {**dict(e), "meta": json.loads(e["meta"]) if e["meta"] else None} for e in events
        ],
    }