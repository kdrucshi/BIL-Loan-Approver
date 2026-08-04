"""
Layer B tests (Evaluation_Engine.md section 11): pytest proves the pipeline's
INPUT computation is correct - Rego proves the rules are correct given
correct inputs. Run with: pytest tests/
"""

from decimal import Decimal

import pytest

from pipeline.compute_inputs import HqCountryMismatch, compute_rule_inputs
from pipeline.fx import FxRates


@pytest.fixture
def fx():
    return FxRates(
        rates={"EUR": Decimal("1"), "USD": Decimal("1.1"), "GBP": Decimal("0.85")},
        rate_date="2026-08-03",
        source="test-fixture",
        stale=False,
    )


@pytest.fixture
def companies():
    return {
        "Acme Ltd": {"company_name": "Acme Ltd", "hq_country": "Germany", "industry": "Test", "assets": []},
    }


def test_fx_conversion_known_rate(fx):
    # 110 USD at rate 1.1 -> exactly 100.00 EUR
    result = fx.to_eur(Decimal("110.00"), "USD")
    assert result == Decimal("100.00")


def test_eur_passthrough_no_conversion(fx):
    # An EUR loan is not sent through FX - no accidental round-trip.
    result = fx.to_eur(Decimal("12345.67"), "EUR")
    assert result == Decimal("12345.67")


def test_rounding_is_round_half_up(fx):
    # 100 USD at rate 1.15 -> 86.9565... -> should round to 86.96 (half up)
    fx_odd = FxRates(rates={"EUR": Decimal("1"), "USD": Decimal("1.15")}, rate_date="x", source="x", stale=False)
    result = fx_odd.to_eur(Decimal("100.00"), "USD")
    assert result == Decimal("86.96")


def test_currency_resolution_eurozone_company(fx, companies):
    loan = {
        "loan_id": "L1", "company_name": "Acme Ltd", "hq_country": "Germany",
        "loan_value": "1000.00", "loan_currency": "EUR", "asset_value": "600.00",
    }
    result = compute_rule_inputs(loan, companies, fx)
    assert result["expected_currency"] == "EUR"
    assert result["mismatch"] is None


def test_csv_pdf_hq_country_mismatch_is_flagged_not_silently_fixed(fx, companies):
    loan = {
        "loan_id": "L1", "company_name": "Acme Ltd", "hq_country": "France",  # CSV disagrees with PDF's "Germany"
        "loan_value": "1000.00", "loan_currency": "EUR", "asset_value": "600.00",
    }
    result = compute_rule_inputs(loan, companies, fx)
    assert isinstance(result["mismatch"], HqCountryMismatch)
    # PDF is still authoritative for the actual currency resolution:
    assert result["expected_currency"] == "EUR"  # Germany's currency, not France's (same here, but proves PDF wins)


def test_coverage_input_uses_original_loan_value_not_eur(fx, companies):
    """The two-value trap (Evaluation_Engine.md section 7): loan_value_eur
    feeds Rule 1 only; the ORIGINAL loan_value feeds Rule 3 alongside
    asset_value - conflating them is the easiest silent bug."""
    loan = {
        "loan_id": "L1", "company_name": "Acme Ltd", "hq_country": "Germany",
        "loan_value": "1000.00", "loan_currency": "USD", "asset_value": "600.00",
    }
    result = compute_rule_inputs(loan, companies, fx)
    assert result["opa_input"]["loan_value"] == 1000.00  # original currency, unconverted
    assert result["opa_input"]["loan_value_eur"] != 1000.00  # converted, different number
    assert result["opa_input"]["asset_value"] == 600.00
