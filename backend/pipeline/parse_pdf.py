"""
Parse company-reference.pdf into companies.json.

Per Evaluation_Engine.md:
- Section 1: reference is static, parse ONCE, never re-parse per loan.
- Section 9: assets are a catalog, not an allocation ledger. Deduplicate by
  (asset_description, asset_value), dropping asset_owner entirely - the same
  physical asset repeats under different owner labels across rows, and no
  rule reads asset_owner, so it is dropped rather than normalised.

Page layout (verified against the real file with pdfplumber):
    Page 1        - cover / title page
    Pages 2-4     - index tables (ID, Company, HQ Country)
    Pages 5-104   - one company profile per page:

        C001 — Yarrow Auto Parts
        Headquarters country Germany
        Industry Pharmaceuticals
        Pledgeable assets
        Asset Value Currency
        Stuttgart Freight Hub 675,069 EUR
        ...
        Related entities
        The following entities may appear as the recorded owner of an asset
        pledged by Yarrow Auto Parts: Yarrow Auto Parts.
"""

import json
import re
from pathlib import Path

import pdfplumber

DASH = "—"  # em dash in "C001 — Yarrow Auto Parts"


def parse_pdf(pdf_path: str = "../data/company-reference.pdf") -> list[dict]:
    companies = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not text.strip():
                continue
            first_line = text.split("\n", 1)[0]
            if DASH not in first_line:
                continue  # cover/index page, not a company profile
            companies.append(_parse_company_page(text))
    return companies


def _parse_company_page(text: str) -> dict:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    company_id, company_name = (part.strip() for part in lines[0].split(DASH, 1))

    hq_country = None
    industry = None
    raw_assets: list[dict] = []
    section = None

    for line in lines[1:]:
        if line.startswith("Headquarters country"):
            hq_country = line[len("Headquarters country"):].strip()
        elif line.startswith("Industry"):
            industry = line[len("Industry"):].strip()
        elif line == "Pledgeable assets":
            continue
        elif line == "Asset Value Currency":
            section = "assets"
        elif line == "Related entities":
            section = "related"
        elif section == "assets":
            raw_assets.append(_parse_asset_line(line))
        # "related" section (asset_owner source) is intentionally NOT parsed
        # into companies.json - it's noise no rule reads (section 9).

    assets = _dedupe_assets(raw_assets)

    return {
        "id": company_id,
        "company_name": company_name,
        "hq_country": hq_country,
        "industry": industry,
        "assets": assets,
    }


def _parse_asset_line(line: str) -> dict:
    description, value_str, currency = line.rsplit(" ", 2)
    return {
        "description": description,
        "value": float(value_str.replace(",", "")),
        "currency": currency,
    }


def _dedupe_assets(raw_assets: list[dict]) -> list[dict]:
    """Collapse duplicate (description, value) pairs into one entry.

    On this data the raw per-page asset list is already distinct per company
    (asset_owner duplication happens in loans.csv, not in the PDF's asset
    table), but dedup here defensively in case a future reference PDF lists
    the same asset twice.
    """
    seen: dict[tuple[str, float], dict] = {}
    for asset in raw_assets:
        key = (asset["description"], asset["value"])
        seen.setdefault(key, asset)
    return list(seen.values())


def build_and_cache(
    pdf_path: str = "../data/company-reference.pdf",
    cache_path: str = "../data/companies.json",
) -> list[dict]:
    companies = parse_pdf(pdf_path)
    Path(cache_path).write_text(json.dumps(companies, indent=2))
    return companies


def load_cached(cache_path: str = "../data/companies.json") -> dict[str, dict]:
    """Load the cached JSON, keyed by company_name for O(1) lookup."""
    companies = json.loads(Path(cache_path).read_text())
    return {c["company_name"]: c for c in companies}


if __name__ == "__main__":
    companies = build_and_cache()
    print(f"Parsed {len(companies)} companies -> data/companies.json")
