"""
Batch client for OPA's /v1/data/compliance/results endpoint.

Sends up to 500 loans in ONE request (Evaluation_Engine.md section 7) -
the per-request round-trip overhead, not the rule evaluation itself, is the
real cost at 100k loans. A shared requests.Session with connection pooling
avoids the connection-churn slowdown a naive per-request client hits at scale.
"""

import requests
from requests.adapters import HTTPAdapter

OPA_URL = "http://localhost:8181/v1/data/compliance/results"

_session = requests.Session()
_session.mount("http://", HTTPAdapter(pool_connections=1, pool_maxsize=10))


class OpaError(RuntimeError):
    pass


def evaluate_batch(loan_inputs: list[dict], timeout: float = 15.0) -> dict[str, dict]:
    """POST a batch of loan inputs, get back {loan_id: {rule1, rule2, rule3}}.

    Verdicts are mapped by `loan_id` key in the response, never by array
    order - the one bug-prone spot the doc calls out explicitly.
    """
    try:
        resp = _session.post(
            OPA_URL, json={"input": {"loans": loan_inputs}}, timeout=timeout
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OpaError(
            f"Could not reach OPA at {OPA_URL}. Is `docker compose up -d` running? ({exc})"
        ) from exc

    result = resp.json().get("result")
    if result is None:
        raise OpaError(f"Unexpected OPA response: {resp.json()}")
    return result
