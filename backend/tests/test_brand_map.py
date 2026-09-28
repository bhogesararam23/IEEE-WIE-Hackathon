"""Unit tests for brand -> ingredient normalisation. No database required.

These are the cheapest tests in the suite and the ones most worth having, because
reconciliation is the part of this feature that quietly produces wrong clinical
data: a missed match means a missed duplicate, and a bad match means a false
duplicate that a user has to clear by hand.
"""

import pytest

from app.services.brand_map import (
    DEFAULT_FUZZY_THRESHOLD,
    normalize_medicine,
    reload_table,
    table_size,
)


def test_seed_table_loaded() -> None:
    """The CSV ships with the app and parses into rows."""
    assert table_size() >= 10, "the brief asked for a 10-20 row seed table"


@pytest.mark.parametrize(
    ("raw_name", "strength", "expected"),
    [
        # The canonical example from the brief.
        ("Crocin 500mg", "500mg", "Paracetamol"),
        # Same drug, other brands. This is the whole point of the table.
        ("Dolo 650", "650mg", "Paracetamol"),
        ("Calpol 650", "650mg", "Paracetamol"),
        # Brand written without its strength.
        ("Crocin", None, "Paracetamol"),
        # Case and OCR noise.
        ("CROCiN 500", "500", "Paracetamol"),
        ("Tab Crocin 500", "500mg", "Paracetamol"),
        # Multi-word brand with a dose token that must be stripped.
        ("Ecosprin AV 75", None, "Acetylsalicylic Acid"),
        # A different drug entirely, to prove the cases are not all Paracetamol.
        ("Restyl 0.5", None, "Lorazepam"),
        ("Ativan 0.5mg", "0.5mg", "Lorazepam"),
        ("Thyronorm 50", None, "Levothyroxine"),
        # The generic name, typed by a user rather than read off a label. Has no
        # CSV row of its own and must still resolve.
        ("Paracetamol 500mg", "500mg", "Paracetamol"),
        ("paracetamol", None, "Paracetamol"),
    ],
)
def test_known_names_resolve(
    raw_name: str, strength: str | None, expected: str
) -> None:
    result = normalize_medicine(raw_name, strength)
    assert result.matched, f"{raw_name!r} did not match anything"
    assert result.ingredient == expected


def test_caller_strength_wins_over_table_default() -> None:
    """A user who typed 650mg means 650mg, not whatever the CSV row says.

    Overwriting the dose from a seed-table default would silently corrupt a
    medication the user is about to rely on.
    """
    result = normalize_medicine("Crocin", "650mg")
    assert result.ingredient == "Paracetamol"
    assert result.strength == "650mg"


def test_falls_back_to_table_strength_when_none_given() -> None:
    result = normalize_medicine("Crocin", None)
    assert result.strength == "500mg"


@pytest.mark.parametrize("raw_name", [None, "", "   "])
def test_blank_input_does_not_match(raw_name: str | None) -> None:
    result = normalize_medicine(raw_name, "500mg")
    assert result.matched is False
    assert result.ingredient is None
    # The best-effort score may be anything; the contract is that it did not match.
    assert result.match_kind == "none"


def test_unrelated_text_does_not_match() -> None:
    """An unknown drug must stay unnormalised, not be force-fitted.

    A wrong ingredient creates a duplicate flag against whatever it collides
    with, which is worse than a missed duplicate: the user has to notice and
    dismiss it.
    """
    result = normalize_medicine("some unknown herbal xyz", None)
    assert result.matched is False
    assert result.ingredient is None


def test_fuzzy_match_is_labelled_as_such() -> None:
    """A fuzzy hit is reported as fuzzy, so a caller can flag it for review."""
    result = normalize_medicine("Crocin 500", "500")
    assert result.matched is True
    assert result.ingredient == "Paracetamol"
    assert result.match_kind == "fuzzy"
    assert result.needs_review is True


def test_exact_match_is_not_flagged_for_review() -> None:
    result = normalize_medicine("Crocin 500mg", "500mg")
    assert result.match_kind == "exact"
    assert result.needs_review is False


def test_threshold_rejects_a_weak_brand_match() -> None:
    """The threshold gates the fuzzy pass, and is a real gate.

    "Crocin 500" only matches through the fuzzy pass (scoring 90 against the
    alias "crocin"), so raising the threshold above 90 must stop it resolving.
    An exact hit is unaffected by design -- the threshold exists to catch
    near-misses, not to second-guess an exact match.
    """
    assert normalize_medicine("Crocin 500", "500").score >= DEFAULT_FUZZY_THRESHOLD
    assert normalize_medicine("Crocin 500", "500").matched is True

    # Inputs that resolve *only* through the fuzzy pass, so the threshold decides.
    for raw in ("Crocin 500", "Dolo 65", "Restyl 05", "Pan 4"):
        assert normalize_medicine(raw, None, threshold=99.5).matched is False, raw

    # Exact matches bypass the fuzzy threshold entirely.
    assert normalize_medicine("Crocin", None, threshold=99.5).matched is True


def test_two_brands_of_one_ingredient_collapse_to_the_same_value() -> None:
    """The reconciliation property, stated directly.

    Duplicate detection compares normalized_ingredient, so this is the assertion
    that actually guarantees a Crocin/Dolo collision is detectable.
    """
    crocin = normalize_medicine("Crocin 500mg", "500mg")
    dolo = normalize_medicine("Dolo 650", "650mg")
    assert crocin.ingredient == dolo.ingredient == "Paracetamol"


def test_reload_clears_the_cache() -> None:
    """The cache is droppable, which is what makes the table testable."""
    before = table_size()
    reload_table()
    assert table_size() == before
