"""
MnemNet — living memory layer for AI agents.

Built on top of mempalace. Adds temporal decay, contradiction tension,
and a predictive layer (expectations + surprises) to the Knowledge Graph.

Quick start:
    from mnemnet import living_context, kg_add_smart, add_expectation, add_surprise

    # Inject weighted context into your agent's system prompt
    context = living_context(["agent", "user"])

    # Add a fact (auto-detects contradictions)
    result = kg_add_smart("agent", "mood", "curious")
    if result["tension"]:
        print(f"tension detected: {result['tension']}")

    # Record an expectation
    add_expectation("user", "will return to the project this week")

    # Record a surprise
    add_surprise("user", "tired", "came in with energy")
"""

from .memory import (
    living_context,
    kg_add_smart,
    kg_query_weighted,
    kg_query_summary,
    get_tensions,
    add_expectation,
    add_surprise,
    get_expectations,
)

__all__ = [
    "living_context",
    "kg_add_smart",
    "kg_query_weighted",
    "kg_query_summary",
    "get_tensions",
    "add_expectation",
    "add_surprise",
    "get_expectations",
]

__version__ = "0.1.0"
