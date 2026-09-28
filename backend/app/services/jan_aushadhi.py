"""Jan Aushadhi (PMBJP) generic-medicine price lookup.

Sits behind the same kind of interface boundary as ``app.services.interactions``:
callers only see :func:`lookup_generic`, so the data source (a small curated CSV
today, the live PMBI product-portfolio catalogue tomorrow) can be swapped by
replacing ``_load_generics`` alone.

The seed CSV is a hand-curated subset covering the ingredients already present
in ``indian_brand_ingredient_map.csv``, priced from the government's published
PMBJP product list (see ``jan_aushadhi_generics.csv``'s row count and
``backend/README.md``'s known limitations for how small "curated" actually is)
-- not the full ~2,110-product catalogue, and not a live feed.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["JanAushadhiOption", "lookup_generic"]

_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "jan_aushadhi_generics.csv"
)


@dataclass(frozen=True, slots=True)
class JanAushadhiOption:
    """One row from the seed CSV: a generic product available under PMBJP."""

    product_name: str
    unit: str
    mrp_inr: float


@lru_cache(maxsize=1)
def _load_generics() -> dict[str, JanAushadhiOption]:
    """Load the seed CSV once per process, keyed by lowercased ingredient."""
    if not _CSV_PATH.is_file():
        logger.error("jan_aushadhi_generics.csv not found at %s", _CSV_PATH)
        return {}

    table: dict[str, JanAushadhiOption] = {}
    with _CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            ingredient = (row.get("generic_ingredient") or "").strip()
            product_name = (row.get("product_name") or "").strip()
            unit = (row.get("unit") or "").strip()
            mrp_raw = (row.get("mrp_inr") or "").strip()
            if not (ingredient and product_name and unit and mrp_raw):
                logger.warning("Skipping malformed row at line %d", lineno)
                continue
            try:
                mrp = float(mrp_raw)
            except ValueError:
                logger.warning("Bad mrp_inr %r at line %d; skipping", mrp_raw, lineno)
                continue
            table[ingredient.lower()] = JanAushadhiOption(
                product_name=product_name, unit=unit, mrp_inr=mrp
            )
    logger.info("Loaded %d Jan Aushadhi generic(s) from %s", len(table), _CSV_PATH.name)
    return table


def lookup_generic(normalized_ingredient: str | None) -> JanAushadhiOption | None:
    """Return the PMBJP generic option for an ingredient, if the seed data has one."""
    if not normalized_ingredient:
        return None
    return _load_generics().get(normalized_ingredient.strip().lower())
