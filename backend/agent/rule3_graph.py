"""
Rule 3 remediation graph - the ONLY place an LLM makes a judgement call in
this system (Action_Engine.md section 2). Rule 1 (remove) and Rule 2 (table
lookup) need no agent at all and are handled by plain functions in
review_actions.py, not this graph - running them through LangGraph would be
pure theater with zero decision for the agent to make.

Flow: retrieve + filter (deterministic tools) -> LLM selects + explains
(only real agent work) -> human interrupt (required gate) -> apply -> OPA
re-check. Confirmed against the Day-1 spike in spike_hitl.py.
"""

import json
from decimal import Decimal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from agent import llm_client, tools


class Rule3State(TypedDict):
    loan_id: str
    company_name: str
    loan_value: float
    loan_currency: str
    candidates: list[dict]
    suggestion_text: str
    suggested_asset: dict | None
    reasoning: str
    confidence: int | None
    via: str | None  # "llm" | "fallback" | None (dead-end, nothing to pick)
    decision: str | None
    manual_value: dict | None
    applied: dict | None


def _retrieve_and_filter(state: Rule3State) -> Rule3State:
    assets = tools.retrieve_company_assets(state["company_name"])
    candidates = tools.filter_valid_collateral(assets, Decimal(str(state["loan_value"])))
    return {**state, "candidates": candidates}


def _select_and_explain(state: Rule3State) -> Rule3State:
    candidates = state["candidates"]

    if not candidates:
        # Honest dead-end - no LLM call needed, there's nothing to select.
        return {
            **state,
            "suggested_asset": None,
            "suggestion_text": "No asset held by this company clears the 50% coverage threshold.",
            "reasoning": (
                f"Checked all assets on record for {state['company_name']}; none "
                f"reach {float(state['loan_value']) * 0.5:.2f} {state['loan_currency']} "
                f"(50% of the {state['loan_value']:.2f} {state['loan_currency']} loan)."
            ),
            "confidence": None,  # nothing to be confident about - honest dead-end
            "via": None,
        }

    prompt = (
        f"A loan of {state['loan_value']:.2f} {state['loan_currency']} to "
        f"{state['company_name']} needs a pledged asset worth at least 50% of that "
        f"value ({state['loan_value'] * 0.5:.2f} {state['loan_currency']}).\n\n"
        f"Qualifying assets already on file for this company:\n"
        + "\n".join(f"{i}. {a['description']} - {a['value']:.2f} {a['currency']}" for i, a in enumerate(candidates))
        + "\n\nPick the single best substitute (prefer the smallest asset that "
        "still clears the threshold, to avoid over-pledging collateral). Also "
        "rate your confidence in this pick from 0-100 (100 = only one qualifying "
        "asset existed or the choice is unambiguous; lower if several assets were "
        "close substitutes). "
        'Respond with ONLY compact JSON: {"index": <int>, "explanation": "<one sentence citing the numbers>", "confidence": <int 0-100>}'
    )
    try:
        raw = llm_client.complete(
            [
                {"role": "system", "content": "You select loan collateral substitutes. Always respond with the exact JSON shape requested, nothing else."},
                {"role": "user", "content": prompt},
            ],
            # The one place an LLM makes a real judgement call - see the
            # MODEL_CHAT / MODEL_ORCHESTRATOR comment in agent/llm_client.py.
            model=llm_client.MODEL_ORCHESTRATOR,
        )
        parsed = json.loads(raw)
        chosen = candidates[int(parsed["index"])]
        explanation = parsed["explanation"]
        confidence = max(0, min(100, int(parsed["confidence"])))
        via = "llm"
    except Exception:  # noqa: BLE001 - ANY LLM failure (parse error, timeout,
        # network/API error) degrades to the deterministic fallback rather
        # than raising - a batch/LLM outage must never block a suggestion.
        # Fallback intentionally picks the SMALLEST qualifying asset (avoids
        # over-pledging collateral) - same choice the LLM is asked to prefer.
        # No confidence value: a fallback pick was never rated by the model.
        chosen = min(candidates, key=lambda a: a["value"])
        explanation = (
            f"{chosen['description']} ({chosen['value']:.2f} {chosen['currency']}) "
            "is the smallest asset on file that still clears the 50% threshold."
        )
        confidence = None
        via = "fallback"

    return {
        **state,
        "suggested_asset": chosen,
        "suggestion_text": f"Substitute asset: {chosen['description']} ({chosen['value']:.2f} {chosen['currency']})",
        "reasoning": explanation,
        "confidence": confidence,
        "via": via,
    }


def _human_review(state: Rule3State) -> Rule3State:
    payload = interrupt(
        {
            "loan_id": state["loan_id"],
            "suggestion_text": state["suggestion_text"],
            "reasoning": state["reasoning"],
        }
    )
    return {**state, "decision": payload.get("decision"), "manual_value": payload.get("manual_value")}


def _apply(state: Rule3State) -> Rule3State:
    if state["decision"] == "accept" and state["suggested_asset"] is not None:
        applied = {
            "asset_description": state["suggested_asset"]["description"],
            "asset_value": state["suggested_asset"]["value"],
        }
    elif state["decision"] == "manual":
        applied = state["manual_value"]
    else:  # "ignore", or accept with no asset available
        applied = None
    return {**state, "applied": applied}


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        g = StateGraph(Rule3State)
        g.add_node("retrieve_and_filter", _retrieve_and_filter)
        g.add_node("select_and_explain", _select_and_explain)
        g.add_node("human_review", _human_review)
        g.add_node("apply", _apply)
        g.set_entry_point("retrieve_and_filter")
        g.add_edge("retrieve_and_filter", "select_and_explain")
        g.add_edge("select_and_explain", "human_review")
        g.add_edge("human_review", "apply")
        g.add_edge("apply", END)
        _graph = g.compile(checkpointer=MemorySaver())
    return _graph


def generate_suggestion(run_id: str, loan_id: str, company_name: str, loan_value: float, loan_currency: str) -> dict:
    """Runs the graph up to (and including) the human_review interrupt,
    returning the suggestion for the review app to show. Wave 1/Wave 2
    scheduling (Action_Engine.md section 7) is the caller's job - this
    function just generates one suggestion."""
    graph = get_graph()
    config = {"configurable": {"thread_id": f"{run_id}:{loan_id}"}}
    result = graph.invoke(
        {
            "loan_id": loan_id,
            "company_name": company_name,
            "loan_value": loan_value,
            "loan_currency": loan_currency,
            "candidates": [],
            "suggestion_text": "",
            "suggested_asset": None,
            "reasoning": "",
            "confidence": None,
            "via": None,
            "decision": None,
            "manual_value": None,
            "applied": None,
        },
        config,
    )
    return result


def resume_with_decision(run_id: str, loan_id: str, decision: str, manual_value: dict | None = None) -> dict:
    """Resumes a paused graph with the reviewer's decision: 'accept' | 'manual' | 'ignore'."""
    graph = get_graph()
    config = {"configurable": {"thread_id": f"{run_id}:{loan_id}"}}
    return graph.invoke(Command(resume={"decision": decision, "manual_value": manual_value}), config)
