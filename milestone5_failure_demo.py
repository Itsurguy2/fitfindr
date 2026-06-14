"""
milestone5_failure_demo.py

Deliberately triggers each of FitFindr's three failure modes and shows the agent
recovering gracefully — no Python exceptions, every failure produces a specific,
informative response. Run this to reproduce the Milestone 5 evidence.

    python milestone5_failure_demo.py

(The output is also what to screenshot / show in the demo video.)
"""

import sys

from tools import search_listings, suggest_outfit, create_fit_card
from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

# Windows consoles default to cp1252 and choke on emoji; force UTF-8.
sys.stdout.reconfigure(encoding="utf-8")


def banner(n, title):
    print("\n" + "=" * 70)
    print(f"FAILURE MODE {n}: {title}")
    print("=" * 70)


# ── 1. search_listings → zero results (and the full agent's response) ───────────
banner(1, "search_listings returns zero results")
results = search_listings("designer ballgown", size="XXS", max_price=5)
print(f"search_listings('designer ballgown', size='XXS', max_price=5) -> {results}")
assert results == [], "expected empty list"
assert isinstance(results, list), "expected a list, not an exception"
print("PASS  returned [] with no exception")

print("\n-- full agent on the same impossible query --")
session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
print(f"session['error']   : {session['error']}")
print(f"session['fit_card']: {session['fit_card']}")
print(f"session['outfit']  : {session['outfit_suggestion']}")
assert session["error"] is not None, "agent should set a specific error"
assert session["fit_card"] is None, "fit_card must stay None"
assert session["outfit_suggestion"] is None, "outfit must stay None"
print("PASS  agent gives an actionable message; LLM tools never run")


# ── 2. suggest_outfit → empty wardrobe ─────────────────────────────────────────
banner(2, "suggest_outfit with an EMPTY wardrobe")
item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
advice = suggest_outfit(item, get_empty_wardrobe())
print(advice)
assert isinstance(advice, str) and advice.strip(), "expected a non-empty string"
print("\nPASS  returned general styling advice (non-empty string), no exception")


# ── 3. create_fit_card → empty outfit string ───────────────────────────────────
banner(3, "create_fit_card with an EMPTY outfit string")
card = create_fit_card("", item)
print(card)
assert isinstance(card, str) and card.strip(), "expected a descriptive error string"
assert "no outfit" in card.lower(), "expected a descriptive 'no outfit' message"
print("\nPASS  returned a descriptive error string, not an exception")


print("\n" + "=" * 70)
print("ALL THREE FAILURE MODES TRIGGERED — AGENT RECOVERED GRACEFULLY")
print("=" * 70)
