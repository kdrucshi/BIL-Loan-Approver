"""
The one seam every LLM call goes through (Action_Engine.md section 12).
Switching provider is a config change here, never a rewrite elsewhere.

Using Azure OpenAI directly (already confirmed working against the
facilitator's endpoint for all 5 models) rather than a Grok/Groq stand-in -
this repo's own docs recommend abstracting behind one interface regardless
of provider, and Azure is both already live and where the doc says
production runs, so there's no migration step to plan for.
"""

import os

from openai import AzureOpenAI

# Single place every model name is chosen - the three call sites (page
# assistant, insights AI summary, Rule 3 orchestrator) all import these
# instead of hardcoding a model string, so swapping a deployment name is a
# one-line change here rather than a hunt across the codebase.
#
# MODEL_CHAT          - short, grounded narration/Q&A: the page assistant
#                       (main.py /api/assistant) and the Insights AI summary
#                       (main.py /api/insights/fx-fragility/summary).
# MODEL_ORCHESTRATOR  - the Rule 3 LangGraph agent (rule3_graph.py), the one
#                       place in the system that makes a real judgement call
#                       (selecting + explaining a substitute asset), so it
#                       gets the larger model.
MODEL_CHAT = os.environ.get("AZURE_OPENAI_CHAT_MODEL", "gpt-5.4-mini")
MODEL_ORCHESTRATOR = os.environ.get("AZURE_OPENAI_ORCHESTRATOR_MODEL", "gpt-5.4")

_client: AzureOpenAI | None = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        )
    return _client


def complete(messages: list[dict], model: str | None = None, max_completion_tokens: int = 400) -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": "..."}]

    All prompt-building, tool-call parsing, and retry logic live on the
    caller's side of this seam - this function only knows how to talk to
    the configured provider.
    """
    client = _get_client()
    model = model or MODEL_CHAT
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_completion_tokens,
    )
    return resp.choices[0].message.content or ""
