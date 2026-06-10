"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Same free model used in Project 1.
MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _call_llm(prompt: str, temperature: float = 0.7) -> str:
    """
    Send a single user prompt to the model and return the text it gives back.

    Raises on any client or API problem so the calling tool can catch it and
    fall back gracefully — tools never let an LLM error crash the agent.
    """
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("Model returned an empty completion.")
    return text


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Filter by price and size first, before any scoring.
    candidates = []
    for item in listings:
        if max_price is not None and item["price"] > max_price:
            continue
        if size is not None and size.strip():
            # Case-insensitive substring match: "M" matches "S/M".
            if size.strip().lower() not in item["size"].lower():
                continue
        candidates.append(item)

    # Score remaining candidates by keyword overlap with the description.
    keywords = _keywords(description)
    scored = []
    for item in candidates:
        score = _relevance_score(item, keywords)
        if score > 0:            # drop anything with no relevant match
            scored.append((score, item))

    # Highest score first.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored]


def _keywords(text: str) -> list[str]:
    """Lowercase the text and split it into word tokens for matching."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _relevance_score(item: dict, keywords: list[str]) -> int:
    """
    Count how many of the query keywords appear in the listing's searchable
    text (title, description, style_tags, category). Each keyword is counted
    once so a longer description doesn't unfairly outweigh a better match.
    """
    haystack = " ".join([
        item.get("title", ""),
        item.get("description", ""),
        " ".join(item.get("style_tags", [])),
        item.get("category", ""),
    ]).lower()
    return sum(1 for kw in set(keywords) if kw in haystack)


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_line = _describe_item(new_item)
    items = (wardrobe or {}).get("items", [])

    if not items:
        # Empty wardrobe: ask for general styling advice for the item alone.
        prompt = (
            "You're a thoughtful personal stylist. A shopper is considering this "
            f"secondhand piece:\n{item_line}\n\n"
            "They haven't told you anything they already own. Suggest one or two "
            "ways to style it from scratch: the overall vibe, what kinds of "
            "bottoms, shoes, and layers pair well with it, and one concrete "
            "styling tip (how to wear it for shape). Keep it to 2-3 sentences, "
            "warm and specific. Don't invent specific items they own."
        )
    else:
        wardrobe_lines = "\n".join(f"- {_describe_wardrobe_item(w)}" for w in items)
        prompt = (
            "You're a thoughtful personal stylist. A shopper is considering this "
            f"secondhand piece:\n{item_line}\n\n"
            "Here is what's already in their wardrobe:\n"
            f"{wardrobe_lines}\n\n"
            "Suggest one or two complete outfits that pair the new piece with "
            "pieces they already own. Refer to their items by name. Include at "
            "least one concrete styling move (tuck, roll, cuff, layer). Keep it "
            "to 2-4 sentences, warm and specific."
        )

    try:
        return _call_llm(prompt, temperature=0.7)
    except Exception:
        # Never crash the agent on an LLM/API failure — return useful fallback.
        title = new_item.get("title", "this piece") if new_item else "this piece"
        return (
            f"Couldn't generate a styling idea right now, but {title} would pair "
            "well with neutral basics, your go-to denim, and a pair of everyday "
            "sneakers or boots."
        )


def _describe_item(item: dict | None) -> str:
    """Format a listing dict into a one-line description for an LLM prompt."""
    if not item:
        return "(no item provided)"
    colors = ", ".join(item.get("colors", []))
    tags = ", ".join(item.get("style_tags", []))
    return (
        f"{item.get('title', 'Unknown item')} "
        f"(category: {item.get('category', 'n/a')}; colors: {colors or 'n/a'}; "
        f"style: {tags or 'n/a'})"
    )


def _describe_wardrobe_item(item: dict) -> str:
    """Format a wardrobe item into a one-line description for an LLM prompt."""
    colors = ", ".join(item.get("colors", []))
    note = item.get("notes")
    line = f"{item.get('name', 'item')} ({item.get('category', 'n/a')}, {colors or 'n/a'})"
    if note:
        line += f" — {note}"
    return line


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no usable outfit to caption.
    if not outfit or not outfit.strip():
        return "Can't make a fit card yet, no outfit suggestion was provided."

    new_item = new_item or {}
    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    platform = new_item.get("platform", "secondhand")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a great price"

    prompt = (
        "Write a short, casual caption for a thrifted outfit, the kind of thing "
        "someone would actually post on Instagram or TikTok with their OOTD. "
        "Keep it to 2-4 sentences. Sound like a real person, not a product "
        "description. Lowercase and a couple of emojis are fine.\n\n"
        f"The find: {title}, picked up on {platform} for {price_str}.\n"
        f"How they're styling it: {outfit}\n\n"
        f"Mention the item, the price ({price_str}), and the platform "
        f"({platform}) naturally, once each. Capture the vibe of the outfit in "
        "specific terms."
    )

    try:
        # Higher temperature so re-runs and different inputs read differently.
        return _call_llm(prompt, temperature=1.0)
    except Exception:
        # Fallback caption built straight from the item fields.
        return f"thrifted this {title} off {platform} for {price_str} 🛍️"
