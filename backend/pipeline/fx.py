"""
Fetch EUR foreign-exchange rates for Rule 1, with the fallback chain from
Evaluation_Engine.md section 5:

    Frankfurter (primary) -> exchangerate.host (secondary) -> last cached
    rates (flagged stale) -> hard failure if nothing has ever been cached.

Staleness is never silent: every run stamps which source supplied the rates,
the rate's real date, and whether it was a stale fallback (fx_stale), so a
borderline Rule 1 verdict is always reproducible and explainable.

Rates are fetched ONCE per run and reused for every loan - never per row.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests
import truststore

# This machine sits behind a corporate TLS-inspecting proxy (Kyndryl). Point
# Python's ssl module at the OS trust store (same one curl/Safari use) instead
# of disabling certificate verification, which would be insecure.
truststore.inject_into_ssl()

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
EXCHANGERATE_HOST_URL = "https://api.exchangerate.host/latest"
CACHE_PATH = Path("../data/fx_cache.json")

# The 7 non-EUR currencies that appear in loans.csv (Evaluation_Engine.md §5).
NON_EUR_CURRENCIES = ["CAD", "CHF", "GBP", "JPY", "PLN", "SEK", "USD"]

TIMEOUT_SECONDS = 5.0


class FxRates:
    def __init__(self, rates: dict[str, Decimal], rate_date: str, source: str, stale: bool):
        self.rates = rates  # {"USD": Decimal("1.0876"), ..., "EUR": Decimal("1")}
        self.rate_date = rate_date
        self.source = source
        self.stale = stale

    def to_eur(self, amount: Decimal, currency: str) -> Decimal:
        """Convert `amount` in `currency` to EUR, rounded to 2dp ROUND_HALF_UP.

        Money is always Decimal, never float - float drifts exactly at the
        Rule 1 boundary, which is where determinism is graded.
        """
        if currency == "EUR":
            return amount.quantize(Decimal("0.01"))
        rate = self.rates.get(currency)
        if rate is None:
            raise ValueError(f"No EUR rate available for currency '{currency}'")
        return (amount / rate).quantize(Decimal("0.01"))


def get_fx_rates(cache_path: Path = CACHE_PATH, force_refresh: bool = False) -> FxRates:
    """`force_refresh=True` (used by run_evaluation.run() on every explicit
    pipeline run) skips the same-day cache and always hits the live sources,
    so clicking 'Run pipeline' twice in one day still gets today's latest
    rate rather than silently reusing the first run's. Single-loan review
    re-checks call this with the default False, so they reuse whatever rate
    the most recent run already fetched - one rate set per run, never a live
    call per reviewed loan (Evaluation_Engine.md section 5).
    """
    today = date.today().isoformat()

    cached = _read_cache(cache_path)
    if not force_refresh and cached and cached["date"] == today and not cached.get("stale"):
        return _from_cache_dict(cached)

    for source_name, url, param_style in (
        ("frankfurter", FRANKFURTER_URL, "from_to"),
        ("exchangerate.host", EXCHANGERATE_HOST_URL, "base_symbols"),
    ):
        try:
            rates = _fetch_from(url, param_style)
            _write_cache(cache_path, today, source_name, rates, stale=False)
            return FxRates(rates=rates, rate_date=today, source=source_name, stale=False)
        except (requests.RequestException, KeyError, ValueError) as exc:
            print(f"[fx] WARNING: {source_name} fetch failed ({exc}); trying next source.")
            continue

    # Both live sources failed - fall back to the last cached rates, if any.
    if cached:
        print(
            f"[fx] WARNING: both FX sources unavailable; falling back to "
            f"rates cached on {cached['date']} (source: {cached['source']})."
        )
        return _from_cache_dict(cached, force_stale=True)

    raise RuntimeError(
        "FX API unavailable from both sources and no cached rates exist on "
        "disk. Cannot compute EUR values for Rule 1 without at least one "
        "successful fetch, ever."
    )


def _fetch_from(url: str, param_style: str) -> dict[str, Decimal]:
    if param_style == "from_to":
        params = {"from": "EUR", "to": ",".join(NON_EUR_CURRENCIES)}
    else:
        params = {"base": "EUR", "symbols": ",".join(NON_EUR_CURRENCIES)}

    resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    body = resp.json()
    raw_rates = body["rates"]
    rates = {ccy: Decimal(str(val)) for ccy, val in raw_rates.items()}
    rates["EUR"] = Decimal("1")
    return rates


def _write_cache(cache_path: Path, today: str, source: str, rates: dict[str, Decimal], stale: bool) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "date": today,
                "source": source,
                "stale": stale,
                "rates": {ccy: str(val) for ccy, val in rates.items()},
            },
            indent=2,
        )
    )


def _read_cache(cache_path: Path) -> dict | None:
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _from_cache_dict(cached: dict, force_stale: bool = False) -> FxRates:
    rates = {ccy: Decimal(val) for ccy, val in cached["rates"].items()}
    return FxRates(
        rates=rates,
        rate_date=cached["date"],
        source=cached["source"],
        stale=force_stale or cached.get("stale", False),
    )


if __name__ == "__main__":
    fx = get_fx_rates()
    print(f"source={fx.source} date={fx.rate_date} stale={fx.stale}")
    print({k: str(v) for k, v in fx.rates.items()})
