"""Brand -> generic ingredient normalisation, backed by a static CSV seed table.

This is the reconciliation step: the same drug is written many ways
("Crocin 500mg", "Dolo 650", "Paracetamol 500") and the duplicate detector can
only work once every spelling maps to one canonical ingredient string.

The table is intentionally a CSV checked into the repo rather than a database
table or an external drug API:

* it is small (tens of rows) and changes with a clinical review, not a deploy;
* loading it is one file read, cached for the process lifetime;
* it can be diffed in code review, which is the point for a clinical mapping.

A real deployment would promote this to a curated, versioned table with a
provenance column. The service interface below is what would stay the same.
"""

from __future__ import annotations

import csv
import logging
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

__all__ = [
    "NormalizationResult",
    "normalize_medicine",
    "table_size",
]

CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "indian_brand_ingredient_map.csv"
)

# Below this, a match is noise rather than signal. Measured on the shipped table:
# a clean brand scores 90-100, "Tab Crocin 500" 90, while "some unknown drug xyz"
# scores 38 and a non-brand word 54. 85 sits in the empty gap.
DEFAULT_FUZZY_THRESHOLD = 85.0

# Trailing dose tokens, stripped to reduce "Crocin 500mg" to the alias "crocin"
# so that the brand can be matched whether or not OCR captured the strength.
# Order matters: the long unit forms must be tried before the bare letters.
_DOSE_TOKEN = re.compile(
    r"""^(?:
          \d+(?:\.\d+)?(?:mg|mcg|gm|g|ml|iu|mol|%|mcgm)?
        | \d+(?:[/-]\d+)+
        | (?:x|tab|cap|syp|inj|drop)s?
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
# Words OCR tends to prepend to a drug name.
_NOISE_PREFIX = re.compile(
    r"^\s*(?:tab|tablet|cap|capsule|syrup|syp|inj|injection)\s+", re.IGNORECASE
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _squash(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    "  CROCIIN   500-mg " -> "crocin 500 mg". Punctuation is turned into spaces
    rather than deleted so "500-mg" does not become the nonsense "500mg" by way
    of "500mg"... which it does either way, harmlessly; the real point is that
    the same text always reduces to the same string.
    """
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _brand_alias(brand_name: str) -> str:
    """Reduce "Ecosprin AV 75" to "ecosprin av" by dropping trailing dose tokens."""
    tokens = _squash(brand_name).split()
    while tokens and _DOSE_TOKEN.match(tokens[-1]):
        tokens.pop()
    return " ".join(tokens) or _squash(brand_name)


@dataclass(frozen=True, slots=True)
class _Entry:
    """One row of the seed table, plus the alias we actually match against."""

    brand: str
    alias: str
    ingredient: str
    strength: str | None


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Outcome of resolving a raw name to a canonical ingredient.

    ``matched`` is false when nothing cleared the threshold, in which case the
    remaining fields are None and the caller should leave
    ``normalized_ingredient`` empty. Silently storing a low-confidence guess
    would create phantom duplicates, which are worse than a missed one because
    the user has to clear the false positive by hand.
    """

    matched: bool
    ingredient: str | None
    strength: str | None
    matched_brand: str | None
    match_kind: str  # "exact" | "fuzzy" | "ingredient" | "none"
    score: float

    @property
    def needs_review(self) -> bool:
        """True for a match that was fuzzy rather than exact."""
        return self.matched and self.match_kind == "fuzzy"


@lru_cache(maxsize=1)
def _table() -> tuple[_Entry, ...]:
    """Load and cache the seed table.

    Read once per process. A malformed row is logged and skipped rather than
    taking the whole service down: a typo in one brand should not stop a user
    from confirming a medicine.
    """
    if not CSV_PATH.is_file():  # pragma: no cover - packaging accident
        logger.error("Brand map not found at %s; normalisation disabled", CSV_PATH)
        return ()

    entries: list[_Entry] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        for lineno, row in enumerate(csv.DictReader(handle), start=2):
            brand = (row.get("brand_name") or "").strip()
            ingredient = (row.get("generic_ingredient") or "").strip()
            strength = (row.get("strength") or "").strip() or None
            if not brand or not ingredient:
                logger.warning(
                    "Skipping %s:%d -- blank brand or ingredient", CSV_PATH, lineno
                )
                continue
            entries.append(
                _Entry(
                    brand=brand,
                    alias=_brand_alias(brand),
                    ingredient=ingredient,
                    strength=strength,
                )
            )
    logger.info("Loaded %d brand mappings from %s", len(entries), CSV_PATH.name)
    return tuple(entries)


def table_size() -> int:
    """Number of mappings currently loaded. Exposed for diagnostics/tests."""
    return len(_table())


def _ingredient_index() -> tuple[tuple[str, str | None], ...]:
    """Every distinct ingredient in the table, longest name first.

    Longest-first matters: "Acetylsalicylic Acid" must be tested before a
    hypothetical shorter "Acid" could shadow it. Derived from the table rather
    than declared separately, so adding a row automatically teaches the matcher
    the generic name too -- which is what lets a manually typed
    "Paracetamol 500mg" match without a CSV row of its own.
    """
    seen: dict[str, str | None] = {}
    for entry in _table():
        seen.setdefault(entry.ingredient, entry.strength)
    return tuple(sorted(seen.items(), key=lambda kv: -len(kv[0])))


def normalize_medicine(
    raw_name: str | None,
    strength: str | None = None,
    *,
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> NormalizationResult:
    """Resolve ``raw_name`` to a canonical generic ingredient.

    Three passes, most specific first:

    1. **Exact** alias or brand match on the squashed text.
    2. **Fuzzy** brand match via rapidfuzz ``WRatio``, above ``threshold``.
    3. **Ingredient** substring match, for text that already names the generic
       drug ("Paracetamol 500mg") and so needs no brand lookup.

    ``strength`` is used to disambiguate when the brand appears more than once at
    different doses, and is otherwise ignored -- a strength mismatch must not
    stop a brand match, or "Dolo 650" would fail to resolve to Paracetamol just
    because the CSV row said 500mg.
    """
    entries = _table()
    if not entries or not raw_name:
        return NormalizationResult(False, None, None, None, "none", 0.0)

    cleaned = _NOISE_PREFIX.sub("", raw_name)
    squashed = _squash(f"{cleaned} {strength or ''}").strip()
    name_only = _squash(cleaned)
    if not name_only:
        return NormalizationResult(False, None, None, None, "none", 0.0)

    # --- 1. exact ---------------------------------------------------------
    for candidate in (squashed, name_only):
        for entry in entries:
            if candidate in (entry.alias, _squash(entry.brand)):
                return NormalizationResult(
                    True,
                    entry.ingredient,
                    _pick_strength(entry, strength),
                    entry.brand,
                    "exact",
                    100.0,
                )

    # --- 2. fuzzy brand ---------------------------------------------------
    aliases = [entry.alias for entry in entries]
    match = process.extractOne(name_only, aliases, scorer=fuzz.WRatio, processor=None)
    if match and match[1] >= threshold:
        entry = next(e for e in entries if e.alias == match[0])
        return NormalizationResult(
            True,
            entry.ingredient,
            _pick_strength(entry, strength),
            entry.brand,
            "fuzzy",
            float(match[1]),
        )

    # --- 3. generic ingredient already present in the text ---------------
    for ingredient, canonical_strength in _ingredient_index():
        if ingredient.lower() in squashed:
            return NormalizationResult(
                True,
                ingredient,
                (strength or canonical_strength),
                None,
                "ingredient",
                100.0,
            )

    return NormalizationResult(
        False, None, None, None, "none", match[1] if match else 0.0
    )


def _pick_strength(entry: _Entry, provided: str | None) -> str | None:
    """Prefer the caller's strength, fall back to the table's.

    The CSV strength is a seed default, not gospel: a user who typed "Crocin
    650mg" means 650mg, and overwriting that with the table's 500mg would
    silently corrupt their dose.
    """
    return provided.strip() if provided and provided.strip() else entry.strength


_lock = threading.Lock()


def reload_table() -> None:
    """Drop the cache so the next lookup re-reads the CSV.

    Only for tests and for a future admin "reload reference data" button. The
    lock is belt-and-braces: CPython's GIL already makes the read atomic enough
    for a file swap.
    """
    with _lock:
        _table.cache_clear()
        logger.info(
            "Brand map cache cleared; %d rows will reload on next use", table_size()
        )
