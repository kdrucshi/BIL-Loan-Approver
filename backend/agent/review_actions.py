"""
Apply a reviewer's decision (accept/manual/ignore) for one loan, then ALWAYS
re-run all three rules through OPA (Action_Engine.md section 10 - a Rule 2
fix can flip Rule 1, so we never re-check just the fixed rule). Every
resulting audit event captures the applied change (from/to), not just that
"something was accepted" (section 11).
"""

import json
from decimal import Decimal

from agent import rule3_graph, tools
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


def decide_rule1(run_id: str, loan_id: str, decision: str) -> dict:
    """Rule 1 has no corrected number - the only choices are 'accept' (remove
    the loan from the report) or 'ignore' (keep reporting it anyway)."""
    conn = get_connection()
    if decision == "accept":
        conn.execute("UPDATE loans SET overall_status = 'removed' WHERE loan_id = ?", (loan_id,))
        conn.commit()
        _log(conn, run_id, loan_id, "removed", {"rule": 1, "action": "removed_from_report"})
        conn.execute(
            "INSERT INTO suggestions (loan_id, run_id, rule, suggestion_text, status) "
            "VALUES (?, ?, 1, 'Remove from report', 'accepted') "
            "ON CONFLICT(loan_id, run_id, rule) DO UPDATE SET status = 'accepted'",
            (loan_id, run_id),
        )
        conn.commit()
        return {"loan_id": loan_id, "rule": 1, "status": "removed"}
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
        "(loan_id, run_id, rule, suggestion_text, suggested_value, reasoning, status) "
        "VALUES (?, ?, 3, ?, ?, ?, 'pending')",
        (
            loan_id, run_id, result["suggestion_text"],
            json.dumps(result["suggested_asset"]) if result["suggested_asset"] else None,
            result["reasoning"],
        ),
    )
    conn.commit()
    return {
        "loan_id": loan_id,
        "suggestion_text": result["suggestion_text"],
        "reasoning": result["reasoning"],
        "has_candidate": result["suggested_asset"] is not None,
    }


def decide_rule3(run_id: str, loan_id: str, decision: str, manual_asset: dict | None = None) -> dict:
    conn = get_connection()
    if decision == "ignore":
        _log(conn, run_id, loan_id, "ignored", {"rule": 3, "action": "ignored"})
        return {"loan_id": loan_id, "rule": 3, "status": "ignored"}

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
