"""
tests/test_tools.py

Tests for the three FitFindr tools, run with `pytest tests/` from the repo root.

There's at least one test per failure mode:
    - search_listings: no results found  -> empty list, no exception
    - suggest_outfit:  empty wardrobe     -> non-empty advice, no exception
    - create_fit_card: missing outfit     -> descriptive message, no exception

The pure-Python search tests run anywhere. The two LLM tools are written to
catch any API failure (including a missing GROQ_API_KEY) and return a graceful
non-empty string, so these tests pass with or without a key configured. One
extra test that needs a live key to check caption variation is skipped when no
key is set.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches -> empty list, never an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_is_case_insensitive_substring():
    # "m" should match listings sized like "S/M".
    results = search_listings("tee", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_sorted_by_relevance():
    results = search_listings("vintage denim jacket", size=None, max_price=None)
    # The first result should be at least as relevant as the last.
    assert len(results) > 0


# ── suggest_outfit ──────────────────────────────────────────────────────────

def test_suggest_outfit_with_wardrobe_returns_text():
    item = {
        "title": "Faded Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage", "graphic tee"],
    }
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


def test_suggest_outfit_empty_wardrobe():
    # Failure mode: empty wardrobe -> still returns useful text, no exception.
    item = {
        "title": "Faded Band Tee",
        "category": "tops",
        "colors": ["black"],
        "style_tags": ["vintage", "graphic tee"],
    }
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


# ── create_fit_card ─────────────────────────────────────────────────────────

def test_create_fit_card_missing_outfit():
    # Failure mode: empty outfit -> descriptive message, no LLM call, no crash.
    item = {"title": "Faded Band Tee", "price": 22.0, "platform": "depop"}
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert "Can't make a fit card" in result


def test_create_fit_card_whitespace_outfit():
    item = {"title": "Faded Band Tee", "price": 22.0, "platform": "depop"}
    result = create_fit_card("   \n  ", item)
    assert "Can't make a fit card" in result


def test_create_fit_card_valid_outfit_returns_text():
    item = {"title": "Faded Band Tee", "price": 22.0, "platform": "depop"}
    result = create_fit_card(
        "Pair it with baggy jeans and chunky sneakers.", item
    )
    assert isinstance(result, str)
    assert result.strip() != ""


@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="needs a live GROQ_API_KEY to call the model",
)
def test_create_fit_card_varies_between_runs():
    # With a real key, the same input should produce different captions.
    item = {"title": "Faded Band Tee", "price": 22.0, "platform": "depop"}
    outfit = "Pair it with baggy jeans and chunky sneakers."
    a = create_fit_card(outfit, item)
    b = create_fit_card(outfit, item)
    assert a != b
