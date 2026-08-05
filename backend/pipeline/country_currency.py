"""
Static country -> currency lookup table.

Built by hand from the 18 countries that actually appear in loans.csv
(Evaluation_Engine.md section 6). Deliberately not derived from a service or
an LLM call: the mapping never changes at runtime, so a static table is
faster, deterministic, and free.
"""

COUNTRY_TO_CURRENCY = {
    "Austria": "EUR",
    "Belgium": "EUR",
    "Canada": "CAD",
    "Finland": "EUR",
    "France": "EUR",
    "Germany": "EUR",
    "Ireland": "EUR",
    "Italy": "EUR",
    "Japan": "JPY",
    "Luxembourg": "EUR",
    "Netherlands": "EUR",
    "Poland": "PLN",
    "Portugal": "EUR",
    "Spain": "EUR",
    "Sweden": "SEK",
    "Switzerland": "CHF",
    "United Kingdom": "GBP",
    "United States": "USD",
}


def currency_for_country(country: str) -> str:
    try:
        return COUNTRY_TO_CURRENCY[country]
    except KeyError as exc:
        raise KeyError(
            f"No currency mapping for country '{country}'. "
            "Add it to COUNTRY_TO_CURRENCY in pipeline/country_currency.py."
        ) from exc
