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
    companies, _total_pages = _parse_pdf_with_meta(pdf_path)
    return companies


def _parse_pdf_with_meta(pdf_path: str) -> tuple[list[dict], int]:
    """Same parse as `parse_pdf`, but also returns the PDF's total page
    count - stamped into companies.json so the Review screen's PDF evidence
    panel can show 'page X of TOTAL' without re-opening the PDF per request.
    """
    companies = []
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not text.strip():
                continue
            first_line = text.split("\n", 1)[0]
            if DASH not in first_line:
                continue  # cover/index page, not a company profile
            companies.append(_parse_company_page(text, page.page_number))
    return companies, total_pages


def _parse_company_page(text: str, page_number: int) -> dict:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    company_id, company_name = (part.strip() for part in lines[0].split(DASH, 1))

    hq_country = None
    hq_line = None  # the literal extracted line backing hq_country - real PDF
    # text for the Review screen's evidence panel, never an invented sentence.
    industry = None
    raw_assets: list[dict] = []
    section = None

    for line in lines[1:]:
        if line.startswith("Headquarters country"):
            hq_country = line[len("Headquarters country"):].strip()
            hq_line = line
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
        "pdf_page": page_number,
        "hq_evidence": {"snippet": hq_line, "highlight": hq_country},
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
    companies, total_pages = _parse_pdf_with_meta(pdf_path)
    Path(cache_path).write_text(
        json.dumps({"total_pages": total_pages, "companies": companies}, indent=2)
    )
    return companies


def load_cached(cache_path: str = "../data/companies.json") -> dict[str, dict]:
    """Load the cached JSON, keyed by company_name for O(1) lookup.

    Accepts both the current {"total_pages", "companies"} cache shape and the
    older bare-list shape, so a stale on-disk cache from before this change
    doesn't hard-fail - it just won't have pdf_page/hq_evidence until the
    next rebuild.
    """
    cached = json.loads(Path(cache_path).read_text())
    companies = cached["companies"] if isinstance(cached, dict) else cached
    return {c["company_name"]: c for c in companies}


def load_pdf_total_pages(cache_path: str = "../data/companies.json") -> int | None:
    """The PDF's total page count, stamped alongside companies.json at parse
    time. Returns None for an old-format (bare-list) cache."""
    cached = json.loads(Path(cache_path).read_text())
    return cached.get("total_pages") if isinstance(cached, dict) else None


if __name__ == "__main__":
    companies = build_and_cache()
    print(f"Parsed {len(companies)} companies -> data/companies.json")
