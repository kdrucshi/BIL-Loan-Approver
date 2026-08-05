"""
Apply a reviewer's decision (accept/manual/ignore) for one loan, then ALWAYS
re-run all three rules through OPA (Action_Engine.md section 10 - a Rule 2
fix can flip Rule 1, so we never re-check just the fixed rule). Every
resulting audit event captures the applied change (from/to), not just that
"something was accepted" (section 11).
"""

import json
import threading
from decimal import Decimal

from agent import rule3_graph, tools
from app.queries import _BUCKET_WHERE, _loans_filter_sql
from pipeline.compute_inputs import compute_rule_inputs
from pipeline.db import get_connection
from pipeline.fx import get_fx_rates
from pipeline.parse_pdf import load_cached


class ReviewError(Exception):
    pass


def _reevaluate_and_persist(conn, run_id: str, loan_id: str) -> dict:
    """Recompute rule inputs from the loan's CURRENT row and re-check via
    OPA. Always all 3 rules, never just the one that was fixed."""
    row = conn.execute("SELECT * FROM loans WHERE loan_id = ?", (loan_id,)).fetchone()
    if row is None:
        raise ReviewError(f"Loan '{loan_id}' not found.")

    companies = load_cached()
    fx = get_fx_rates()  # same-day cache, so this reuses the run's rates
    loan_dict = {
        "loan_id": row["loan_id"],
        "company_name": row["company_name"],
        "hq_country": row["hq_country"],
        "loan_value": row["loan_value"],
        "loan_currency": row["loan_currency"],
        "asset_value": row["asset_value"],
    }
    inputs = compute_rule_inputs(loan_dict, companies, fx)
    verdict = tools.reevaluate(inputs["opa_input"])

    rule1_pass, rule2_pass, rule3_pass = (
        verdict["rule1"]["pass"], verdict["rule2"]["pass"], verdict["rule3"]["pass"],
    )
    overall_status = "compliant" if (rule1_pass and rule2_pass and rule3_pass) else "has_failures"

    conn.execute(
        "INSERT OR REPLACE INTO rule_results "
        "(loan_id, run_id, rule1_pass, rule2_pass, rule3_pass, loan_value_eur, expected_currency, coverage_ratio) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            loan_id, run_id, int(rule1_pass), int(rule2_pass), int(rule3_pass),
            str(inputs["loan_value_eur"]), inputs["expected_currency"],
            str(verdict["rule3"]["coverage_ratio"]),
        ),
    )
    conn.execute(
        "UPDATE loans SET overall_status = ? WHERE loan_id = ?", (overall_status, loan_id)
    )
    conn.commit()
    return verdict


def _log(conn, run_id: str, loan_id: str, message: str, meta: dict) -> None:
    conn.execute(
        "INSERT INTO audit_events (run_id, source, loan_id, message, meta) VALUES (?, 'reviewer', ?, ?, ?)",
        (run_id, loan_id, message, json.dumps(meta)),
    )
    conn.commit()


def _mark_removed(conn, run_id: str, loan_id: str, rule: int) -> dict:
    """Shared 'remove from report' path (Rule 1's only remediation, and Rule
    3's dead-end escape hatch): marks the loan out of scope, no OPA re-check
    needed (a removed loan isn't reported at all, so there's nothing to
    re-verify), logs the audit event, and records the suggestions row so the
    review UI/chatbot see it as resolved rather than still-pending."""
    conn.execute("UPDATE loans SET overall_status = 'removed' WHERE loan_id = ?", (loan_id,))
    conn.commit()
    _log(conn, run_id, loan_id, "removed", {"rule": rule, "action": "removed_from_report"})
    conn.execute(
        "INSERT INTO suggestions (loan_id, run_id, rule, suggestion_text, status) "
        "VALUES (?, ?, ?, 'Remove from report', 'accepted') "
        "ON CONFLICT(loan_id, run_id, rule) DO UPDATE SET status = 'accepted'",
        (loan_id, run_id, rule),
    )
    conn.commit()
    return {"loan_id": loan_id, "rule": rule, "status": "removed"}


def decide_rule1(run_id: str, loan_id: str, decision: str) -> dict:
    """Rule 1 has no corrected number - the only choices are 'accept' (remove
    the loan from the report) or 'ignore' (keep reporting it anyway)."""
    conn = get_connection()
    if decision == "accept":
        return _mark_removed(conn, run_id, loan_id, 1)
    else:  # ignore
        _log(conn, run_id, loan_id, "ignored", {"rule": 1, "action": "ignored"})
        return {"loan_id": loan_id, "rule": 2, "status": "ignored"}


def decide_rule2(run_id: str, loan_id: str, decision: str, manual_currency: str | None = None) -> dict:
    conn = get_connection()
    if decision == "ignore":
        _log(conn, run_id, loan_id, "ignored", {"rule": 2, "action": "ignored"})
        return {"loan_id": loan_id, "rule": 2, "status": "ignored"}

    row = conn.execute("SELECT loan_currency FROM loans WHERE loan_id = ?", (loan_id,)).fetchone()
    old_currency = row["loan_currency"]

    if decision == "accept":
        companies = load_cached()
        new_currency = tools.get_expected_currency(
            conn.execute("SELECT company_name FROM loans WHERE loan_id = ?", (loan_id,)).fetchone()["company_name"],
            companies,
        )
    elif decision == "manual":
        if not manual_currency:
            raise ReviewError("manual decision for rule 2 requires manual_currency")
        new_currency = manual_currency
    else:
        raise ReviewError(f"Unknown decision '{decision}' for rule 2")

    conn.execute("UPDATE loans SET loan_currency = ? WHERE loan_id = ?", (new_currency, loan_id))
    conn.commit()

    verdict = _reevaluate_and_persist(conn, run_id, loan_id)
    action = "accepted_ai_fix" if decision == "accept" else "manual_fix"
    _log(conn, run_id, loan_id, action, {"rule": 2, "from": old_currency, "to": new_currency})

    return {"loan_id": loan_id, "rule": 2, "from": old_currency, "to": new_currency, "verdict": verdict}


def generate_rule3_suggestion(run_id: str, loan_id: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT company_name, loan_value, loan_currency FROM loans WHERE loan_id = ?", (loan_id,)
    ).fetchone()
    if row is None:
        raise ReviewError(f"Loan '{loan_id}' not found.")

    result = rule3_graph.generate_suggestion(
        run_id, loan_id, row["company_name"], float(row["loan_value"]), row["loan_currency"]
    )
    conn.execute(
        "INSERT OR REPLACE INTO suggestions "
        "(loan_id, run_id, rule, suggestion_text, suggested_value, confidence, reasoning, status, via, computed_at) "
        "VALUES (?, ?, 3, ?, ?, ?, ?, 'pending', ?, datetime('now'))",
        (
            loan_id, run_id, result["suggestion_text"],
            json.dumps(result["suggested_asset"]) if result["suggested_asset"] else None,
            result.get("confidence"),
            result["reasoning"],
            result.get("via"),
        ),
    )
    conn.commit()
    return {
        "loan_id": loan_id,
        "suggestion_text": result["suggestion_text"],
        "reasoning": result["reasoning"],
        "confidence": result.get("confidence"),
        "via": result.get("via"),
        "has_candidate": result["suggested_asset"] is not None,
    }


def list_company_assets_for_loan(run_id: str, loan_id: str) -> list[dict]:
    """Pure read, no LLM call - the REAL asset catalog for this loan's
    company, with qualifies/coverage computed deterministically (the same
    >= 0.5*loan_value test the pipeline/OPA use). Powers a real asset-picker
    dropdown; never fabricates a candidate the way a client-side mock would."""
    conn = get_connection()
    loan = conn.execute(
        "SELECT company_name, loan_value, asset_description FROM loans WHERE loan_id = ?", (loan_id,)
    ).fetchone()
    if loan is None:
        raise ReviewError(f"Loan '{loan_id}' not found.")

    loan_value = Decimal(loan["loan_value"])
    threshold = loan_value * Decimal("0.5")
    companies = load_cached()
    company = companies.get(loan["company_name"])
    company_pdf_page = company.get("pdf_page") if company else None
    rows = conn.execute(
        "SELECT asset_description, asset_value FROM assets WHERE company_name = ? ORDER BY asset_description",
        (loan["company_name"],),
    ).fetchall()
    return [
        {
            "name": r["asset_description"],
            "value": float(Decimal(r["asset_value"])),
            "qualifies": Decimal(r["asset_value"]) >= threshold,
            "coverage": float(Decimal(r["asset_value"]) / loan_value) if loan_value else 0.0,
            "current": r["asset_description"] == loan["asset_description"],
            "pdfPage": company_pdf_page,
        }
        for r in rows
    ]


def decide_rule3(run_id: str, loan_id: str, decision: str, manual_asset: dict | None = None) -> dict:
    conn = get_connection()
    if decision == "ignore":
        _log(conn, run_id, loan_id, "ignored", {"rule": 3, "action": "ignored"})
        return {"loan_id": loan_id, "rule": 3, "status": "ignored"}
    if decision == "remove":
        # Dead-end escape hatch: no collateral clears 50%, so the loan is
        # taken out of scope entirely rather than forcing a fabricated fix.
        return _mark_removed(conn, run_id, loan_id, 3)

    row = conn.execute(
        "SELECT asset_description, asset_value FROM loans WHERE loan_id = ?", (loan_id,)
    ).fetchone()
    old_asset = {"description": row["asset_description"], "value": float(Decimal(row["asset_value"]))}

    resumed = rule3_graph.resume_with_decision(run_id, loan_id, decision, manual_asset)
    applied = resumed["applied"]
    if applied is None:
        raise ReviewError("No asset available to apply (honest dead-end) or ignore was chosen mid-flow.")

    conn.execute(
        "UPDATE loans SET asset_description = ?, asset_value = ? WHERE loan_id = ?",
        (applied["asset_description"], str(Decimal(str(applied["asset_value"]))), loan_id),
    )
    conn.commit()

    verdict = _reevaluate_and_persist(conn, run_id, loan_id)
    action = "accepted_ai_fix" if decision == "accept" else "manual_fix"
    _log(
        conn, run_id, loan_id, action,
        {"rule": 3, "from": old_asset, "to": applied},
    )
    conn.execute(
        "UPDATE suggestions SET status = ? WHERE loan_id = ? AND run_id = ? AND rule = 3",
        ("accepted" if decision == "accept" else "manual", loan_id, run_id),
    )
    conn.commit()

    return {"loan_id": loan_id, "rule": 3, "from": old_asset, "to": applied, "verdict": verdict}


def _resolve_bulk_loan_ids(
    conn, run_id: str, rule: int,
    loan_ids: list[str] | None, select_all_matching: bool, filter: dict | None, max_loans: int | None,
) -> list[str]:
    """Shared selection-resolution for bulk-generate and bulk-decide, so a
    generate pass and the accept pass that follows it always cover the exact
    same loans - either an explicit `loan_ids` list, or (select_all_matching)
    every loan CURRENTLY matching `filter`, resolved fresh here rather than
    trusting a client-supplied id list, which could be stale by the time the
    request lands (Review screen integration guide, section 6)."""
    if select_all_matching:
        filter = filter or {}
        where = _BUCKET_WHERE[rule]
        filter_sql, filter_params = _loans_filter_sql(
            filter.get("ccy"), filter.get("min"), filter.get("max"), bool(filter.get("low_conf")),
            filter.get("q"),
        )
        query = f"""
            SELECT rr.loan_id FROM rule_results rr
            JOIN loans l ON l.loan_id = rr.loan_id
            LEFT JOIN suggestions s ON s.loan_id = rr.loan_id AND s.run_id = rr.run_id AND s.rule = ?
            WHERE rr.run_id = ? AND l.overall_status = 'has_failures' AND {where}{filter_sql}
        """
        resolved_ids = [r["loan_id"] for r in conn.execute(query, [rule, run_id, *filter_params]).fetchall()]
    else:
        resolved_ids = list(loan_ids or [])
    return resolved_ids[:max_loans] if max_loans is not None else resolved_ids


def bulk_generate_rule3(
    run_id: str,
    loan_ids: list[str] | None = None,
    select_all_matching: bool = False,
    filter: dict | None = None,
    max_loans: int | None = None,
) -> dict:
    """Generates (and persists as 'pending') a Rule 3 substitute-asset
    suggestion for every loan in the selection, WITHOUT applying any of
    them. This is the human-review gate for a batch: the reviewer sees each
    loan's proposed asset (or an honest dead-end) here BEFORE a separate
    bulk_decide(accept) call resumes and applies them - the LLM's pick for a
    whole batch is never generated-and-applied in the same uninspectable
    step (see the architecture note this fixes: bulk_decide used to do both
    in one call, so a reviewer approving "Accept selected" never actually
    saw which asset the LLM chose for each loan)."""
    conn = get_connection()
    resolved_ids = _resolve_bulk_loan_ids(conn, run_id, 3, loan_ids, select_all_matching, filter, max_loans)

    results = []
    for loan_id in resolved_ids:
        try:
            results.append(generate_rule3_suggestion(run_id, loan_id))
        except ReviewError as exc:  # noqa: PERF203 - one bad loan shouldn't abort the whole batch
            results.append({"loan_id": loan_id, "error": str(exc)})
    return {"rule": 3, "requested": len(resolved_ids), "results": results}


def bulk_decide(
    run_id: str,
    rule: int,
    decision: str,
    loan_ids: list[str] | None = None,
    select_all_matching: bool = False,
    filter: dict | None = None,
    max_loans: int | None = None,
) -> dict:
    """Applies ONE decision to a set of loans in a single rule's bucket -
    either an explicit `loan_ids` list, or (select_all_matching=True) every
    loan CURRENTLY matching `filter`, resolved fresh here rather than trusting
    a client-supplied id list, which could be stale by the time the request
    lands (Review screen integration guide, section 6). `filter` uses the
    SAME WHERE-fragment as the paginated /api/review/loans listing
    (queries._loans_filter_sql), so a bulk action never covers more or fewer
    loans than the reviewer currently sees.

    Clubbing batches the click, never erases the per-loan audit trail
    (Action_Engine.md section 8): each loan below still goes through its own
    decide_ruleN call, so it gets its own re-check through OPA and its own
    audit_events row - a bulk action is just this loop, not a shortcut.

    Rule 1 and Rule 2 'accept' are cheap (static table / removal, at most one
    OPA re-check per loan - no LLM). Rule 3 'accept' does NOT generate a
    suggestion here - it requires one to already exist (call
    bulk_generate_rule3 first and let the reviewer see the picks), so the
    LLM's per-loan choice is never generated and applied in the same
    uninspectable step. A loan with no prior suggestion is reported as an
    error rather than silently generated-and-applied.
    """
    if decision not in ("accept", "ignore"):
        raise ReviewError(f"Bulk decision must be 'accept' or 'ignore', got '{decision}'")
    if rule not in (1, 2, 3):
        raise ReviewError(f"rule must be 1, 2, or 3, got {rule}")

    conn = get_connection()
    resolved_ids = _resolve_bulk_loan_ids(conn, run_id, rule, loan_ids, select_all_matching, filter, max_loans)

    applied, errors = [], []
    for loan_id in resolved_ids:
        try:
            if rule == 1:
                decide_rule1(run_id, loan_id, decision)
            elif rule == 2:
                decide_rule2(run_id, loan_id, decision)
            else:  # rule == 3
                if decision == "accept":
                    has_suggestion = conn.execute(
                        "SELECT 1 FROM suggestions WHERE loan_id = ? AND run_id = ? AND rule = 3",
                        (loan_id, run_id),
                    ).fetchone()
                    if not has_suggestion:
                        raise ReviewError(
                            "No suggestion generated yet for this loan - call bulk-generate "
                            "first so the pick can be reviewed before accepting."
                        )
                decide_rule3(run_id, loan_id, decision)
            applied.append(loan_id)
        except ReviewError as exc:  # noqa: PERF203 - one bad loan shouldn't abort the whole batch
            errors.append({"loan_id": loan_id, "error": str(exc)})

    return {
        "rule": rule,
        "decision": decision,
        "requested": len(resolved_ids),
        "applied": len(applied),
        "errors": errors,
    }


# ---------- Rule 3 background wave: non-blocking pre-computation ----------
# Generates suggestions for every still-uncomputed R3 failure in a run, so
# most loans already show a real suggestion by the time a reviewer opens
# them - WITHOUT making /api/run block on thousands of LLM calls. Tracked
# per run_id so the frontend can show overall wave progress, and so a
# per-loan "computing..." state (fix.type==="none" but computed_at is null)
# can be told apart from a genuine, already-checked dead-end.
_wave_progress: dict[str, dict] = {}
_wave_lock = threading.Lock()


def rule3_wave_progress(run_id: str) -> dict:
    return _wave_progress.get(run_id, {"done": 0, "total": 0, "running": False})


def run_rule3_wave(run_id: str) -> None:
    """Meant to be called on a background thread (see main.py) right after
    a pipeline run completes. Idempotent - only ever generates for loans
    that don't already have a Rule 3 suggestion, and refuses to start a
    second concurrent wave for the same run_id."""
    with _wave_lock:
        if _wave_progress.get(run_id, {}).get("running"):
            return
        _wave_progress[run_id] = {"done": 0, "total": 0, "running": True}

    conn = get_connection()
    where = _BUCKET_WHERE[3]
    rows = conn.execute(
        f"""
        SELECT rr.loan_id FROM rule_results rr
        JOIN loans l ON l.loan_id = rr.loan_id
        LEFT JOIN suggestions s ON s.loan_id = rr.loan_id AND s.run_id = rr.run_id AND s.rule = 3
        WHERE rr.run_id = ? AND l.overall_status = 'has_failures' AND {where} AND s.loan_id IS NULL
        """,
        (run_id,),
    ).fetchall()
    loan_ids = [r["loan_id"] for r in rows]
    _wave_progress[run_id] = {"done": 0, "total": len(loan_ids), "running": True}

    for loan_id in loan_ids:
        try:
            generate_rule3_suggestion(run_id, loan_id)
        except ReviewError:
            pass  # skip a bad loan - the wave must not stop for one failure
        _wave_progress[run_id]["done"] += 1

    _wave_progress[run_id]["running"] = False

