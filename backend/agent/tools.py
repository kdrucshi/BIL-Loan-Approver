"""
The deterministic tools the agent calls (Action_Engine.md section 4).
Every factual claim the agent makes traces back to one of these - the agent
orchestrates them, it never replaces them.
"""

from decimal import Decimal

from pipeline import opa_client
from pipeline.country_currency import currency_for_country
from pipeline.parse_pdf import load_cached


def get_expected_currency(company_name: str, companies: dict | None = None) -> str:
    """Rule 2 fix VALUE - never guessed. Company -> PDF HQ country -> static table."""
    companies = companies or load_cached()
    company = companies[company_name]
    return currency_for_country(company["hq_country"])


def retrieve_company_assets(company_name: str, companies: dict | None = None) -> list[dict]:
    """Rule 3 retrieval - structured lookup, not embeddings (see chat history:
    company names match 1:1 between loans.csv and the PDF, verified zero
    mismatches, so exact lookup is the correct, defensible choice)."""
    companies = companies or load_cached()
    company = companies[company_name]
    return company["assets"]


def filter_valid_collateral(assets: list[dict], loan_value: Decimal) -> list[dict]:
    """Rule 3 candidate set: assets clearing >= 0.5 * loan_value."""
    threshold = loan_value * Decimal("0.5")
    return [a for a in assets if Decimal(str(a["value"])) >= threshold]


def reevaluate(opa_input: dict) -> dict:
    """The re-check after any fix - always OPA again, never assumed."""
    result = opa_client.evaluate_batch([opa_input])
    return result[opa_input["loan_id"]]
