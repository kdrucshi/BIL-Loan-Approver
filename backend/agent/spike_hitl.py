"""
Day-1 spike (per Action_Engine.md section 12): confirm LangGraph's
interrupt/checkpoint mechanism behaves as expected for a suggest -> human
interrupt -> apply flow, BEFORE building the real orchestrator on top of it.

This is throwaway/diagnostic, not part of the real agent - kept here as
proof the pattern was verified, and as a reference for the real
orchestrator's shape.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict


class State(TypedDict):
    loan_id: str
    suggestion: str
    decision: str | None
    applied: str | None


def suggest_node(state: State) -> State:
    print(f"[suggest] building suggestion for {state['loan_id']}")
    return {**state, "suggestion": "Change currency to EUR"}


def human_review_node(state: State) -> State:
    # This is the HITL gate: pause execution and surface the suggestion to
    # a human. Whatever value resumes the graph (via Command(resume=...))
    # becomes the return value of interrupt().
    decision = interrupt({"loan_id": state["loan_id"], "suggestion": state["suggestion"]})
    return {**state, "decision": decision}


def apply_node(state: State) -> State:
    if state["decision"] == "accept":
        applied = state["suggestion"]
    elif state["decision"] == "ignore":
        applied = "ignored"
    else:
        applied = f"manual:{state['decision']}"
    print(f"[apply] {state['loan_id']} -> {applied}")
    return {**state, "applied": applied}


def build_graph():
    g = StateGraph(State)
    g.add_node("suggest", suggest_node)
    g.add_node("human_review", human_review_node)
    g.add_node("apply", apply_node)
    g.set_entry_point("suggest")
    g.add_edge("suggest", "human_review")
    g.add_edge("human_review", "apply")
    g.add_edge("apply", END)
    return g.compile(checkpointer=MemorySaver())


def run_spike():
    graph = build_graph()
    config = {"configurable": {"thread_id": "spike-1"}}

    # First invoke runs suggest -> human_review, then PAUSES at interrupt().
    result = graph.invoke({"loan_id": "L000123", "suggestion": "", "decision": None, "applied": None}, config)
    print("after first invoke (should be paused, no 'applied' yet):", result)
    assert "applied" not in result or result.get("applied") is None

    state = graph.get_state(config)
    print("pending interrupts:", state.tasks[0].interrupts if state.tasks else "none")

    # Resume with the human's decision - this is what the review app's
    # "Accept" button would send.
    final = graph.invoke(Command(resume="accept"), config)
    print("after resume with 'accept':", final)
    assert final["applied"] == "Change currency to EUR"

    print("\nSPIKE PASSED: suggest -> interrupt -> resume -> apply works as expected.")


if __name__ == "__main__":
    run_spike()
