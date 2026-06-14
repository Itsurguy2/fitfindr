"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    get_trends,
)
from style_memory import load_style_profile, update_profile_with_item


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a description, optional size, and optional max_price from a natural
    language query using regex. Free/offline/deterministic — no LLM needed.

    "vintage graphic tee under $30, size M"
        → {"description": "vintage graphic tee", "size": "M", "max_price": 30.0}
    """
    text = query.strip()

    # max_price: "under $30", "below 30", "max $25", or a bare "$30".
    max_price = None
    m = re.search(r"(?:under|below|less than|max|<)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    if not m:
        m = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if m:
        max_price = float(m.group(1))

    # size: "size M", "size 8", "in size L".
    size = None
    sm = re.search(r"size\s+([A-Za-z0-9.]+)", text, re.I)
    if sm:
        # Strip trailing punctuation ("size M." -> "M") while preserving
        # decimal sizes like "8.5" (strip only removes leading/trailing chars).
        size = sm.group(1).strip(" .,").upper()

    # description: the query with size/price phrases stripped, then filler words
    # removed. Filler matters here because search does substring matching —
    # short words like "in"/"a" would match inside "vintage"/"denim" and add noise.
    description = re.sub(r"\bsize\s+[A-Za-z0-9.]+", "", text, flags=re.I)
    description = re.sub(
        r"(?:under|below|less than|max|<)\s*\$?\s*\d+(?:\.\d+)?", "", description, flags=re.I
    )
    description = re.sub(r"\$\s*\d+(?:\.\d+)?", "", description)

    _STOPWORDS = {
        "looking", "for", "a", "an", "the", "in", "on", "im", "i'm", "i", "want",
        "wanna", "need", "find", "me", "my", "some", "of", "to", "with",
        "that", "what", "out", "there", "and", "how", "would", "style", "it",
        "is", "are", "something",
    }
    words = [w for w in description.lower().split() if w not in _STOPWORDS]
    description = " ".join(words).strip(" ,.")

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        # stretch features:
        "retry_note": None,          # set if search was auto-loosened to find results
        "price_assessment": None,    # dict from compare_price for the selected item
        "trends_used": [],           # trending tags fed into the outfit suggestion
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the natural-language query into structured params.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search. DECISION POINT — branch on whether anything came back.
    session["search_results"] = search_listings(
        parsed["description"], parsed["size"], parsed["max_price"]
    )

    # Stretch (+1): RETRY WITH FALLBACK. If nothing matched, loosen the
    # constraints one at a time (size first, then price) and record what changed,
    # instead of giving up immediately.
    if not session["search_results"] and parsed["size"] is not None:
        retried = search_listings(parsed["description"], None, parsed["max_price"])
        if retried:
            session["search_results"] = retried
            session["retry_note"] = (
                f"No matches in size {parsed['size']}, so I dropped the size "
                "filter and searched all sizes."
            )
    if not session["search_results"] and parsed["max_price"] is not None:
        retried = search_listings(parsed["description"], None, None)
        if retried:
            session["search_results"] = retried
            session["retry_note"] = (
                f"Nothing under ${parsed['max_price']:.0f}, so I dropped the price "
                "and size filters to show the closest matches."
            )

    if not session["search_results"]:
        # No-results branch (even after retry): specific, actionable error. STOP.
        # We do NOT call suggest_outfit / create_fit_card with empty input.
        relaxers = []
        if parsed["max_price"] is not None:
            relaxers.append("raising your price limit")
        if parsed["size"] is not None:
            relaxers.append("dropping the size filter")
        relaxers.append("trying different keywords")
        session["error"] = (
            f"No listings matched '{parsed['description']}'"
            + (f" under ${parsed['max_price']:.0f}" if parsed["max_price"] else "")
            + (f" in size {parsed['size']}" if parsed["size"] else "")
            + ". Try " + ", or ".join(relaxers) + "."
        )
        return session  # early return — fit_card stays None

    # Step 4: select the top-ranked item (the state hand-off).
    session["selected_item"] = session["search_results"][0]

    # Stretch (+2): PRICE COMPARISON. Judge the selected item's price vs comparable
    # listings in the dataset.
    session["price_assessment"] = compare_price(session["selected_item"])

    # Stretch (+2): STYLE PROFILE MEMORY + TREND AWARENESS. Load remembered prefs
    # (from prior sessions, no re-entry) and current trends, fold the selected
    # item into the saved profile, and feed both into the outfit suggestion.
    style_profile = load_style_profile()
    session["trends_used"] = get_trends(parsed["size"])
    update_profile_with_item(session["selected_item"])

    # Step 5: suggest an outfit using the selected item + the wardrobe,
    # biased by remembered style preferences and current trends.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"],
        session["wardrobe"],
        style_profile=style_profile,
        trends=session["trends_used"],
    )

    # Step 6: turn that outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done — error stays None on the happy path.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
