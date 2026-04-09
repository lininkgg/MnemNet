"""
memory.py — MnemNet core.

Three mechanisms on top of mempalace KG:
  1. Temporal decay    — recent facts are louder, old ones fade to background
  2. Auto-tension      — contradictions are held as tension nodes, not overwritten
  3. Predictive layer  — expectations and surprises as first-class facts
"""

import math
import sys
from datetime import date

try:
    from mempalace.knowledge_graph import KnowledgeGraph
except ImportError:
    print(
        "Error: mempalace is not installed.\n"
        "Install it with: pip install mempalace\n"
        "Then initialize:  mempalace init",
        file=sys.stderr,
    )
    raise SystemExit(1)

from . import config as cfg


class MempalaceNotInitializedError(Exception):
    """Raised when mempalace palace has not been initialized."""
    pass


def _kg() -> KnowledgeGraph:
    """Return a KnowledgeGraph instance from the default palace."""
    try:
        return KnowledgeGraph()
    except Exception as e:
        if "no such table" in str(e).lower() or "database" in str(e).lower():
            raise MempalaceNotInitializedError(
                "mempalace is installed but not initialized.\n"
                "Run: mempalace init"
            ) from e
        raise


# ---------------------------------------------------------------------------
# Temporal decay
# ---------------------------------------------------------------------------

def _decay_weight(valid_from: str | None) -> float:
    """
    Weight a fact by age.
    Returns 1.0 (just created) → cfg.decay.floor (very old).
    """
    if not valid_from:
        return 0.5
    try:
        created = date.fromisoformat(valid_from[:10])
        days = (date.today() - created).days
        weight = math.exp(-cfg.decay.lam * days)
        return max(weight, cfg.decay.floor)
    except Exception:
        return 0.5


def kg_query_weighted(entity: str) -> list[dict]:
    """
    Query the KG and attach a temporal weight to each fact.
    Returns facts sorted loud → quiet.
    """
    kg = _kg()
    rows = kg.query_entity(entity)
    if not rows:
        return []

    weighted = []
    for row in rows:
        weight = _decay_weight(row.get("valid_from"))
        weighted.append({**row, "weight": round(weight, 3)})

    weighted.sort(key=lambda f: f["weight"], reverse=True)
    return weighted


def kg_query_summary(entity: str) -> str:
    """Human-readable weighted echo — ready to inject into a prompt."""
    facts = kg_query_weighted(entity)
    if not facts:
        return f"[{entity}: nothing found]"

    lines = [f"[{entity}]"]
    for f in facts:
        filled = round(f["weight"] * 5)
        bar = "●" * filled + "○" * (5 - filled)
        lines.append(f"  {bar} {f['subject']} —{f['predicate']}→ {f['object']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contradiction → tension
# ---------------------------------------------------------------------------

def kg_add_smart(subject: str, predicate: str, obj: str) -> dict:
    """
    Add a fact with contradiction detection.

    If [subject → predicate → *something else*] already exists,
    both facts are kept and the conflict is recorded as a tension node:
        subject —_tension_<predicate>→ "before: «old» / now: «new»"

    Returns: {"added": True, "tension": str | None}
    """
    today = date.today().isoformat()
    kg = _kg()

    existing = kg.query_entity(subject, direction="outgoing")
    tension = None

    if existing:
        conflicts = [
            f for f in existing
            if f.get("predicate") == predicate
            and f.get("object", "").lower() != obj.lower()
            and f.get("current", True)
        ]
        if conflicts:
            for c in conflicts:
                tension_desc = f"before: «{c['object']}» / now: «{obj}»"
                kg.add_triple(
                    subject=subject,
                    predicate=f"_tension_{predicate}",
                    obj=tension_desc,
                    valid_from=today,
                )
            tension = tension_desc

    kg.add_triple(subject=subject, predicate=predicate, obj=obj, valid_from=today)
    return {"added": True, "tension": tension}


def get_tensions(entity: str) -> list[str]:
    """Return all open tensions for an entity."""
    kg = _kg()
    rows = kg.query_entity(entity, direction="outgoing") or []
    return [
        f"{r['predicate'].replace('_tension_', '')}: {r['object']}"
        for r in rows
        if "_tension_" in r.get("predicate", "")
    ]


# ---------------------------------------------------------------------------
# Predictive layer
# ---------------------------------------------------------------------------

def add_expectation(entity: str, prediction: str) -> None:
    """Record that the agent expects [entity] to [prediction]."""
    kg = _kg()
    kg.add_triple(
        subject=entity,
        predicate="_expectation",
        obj=prediction,
        valid_from=date.today().isoformat(),
    )


def add_surprise(entity: str, expected: str, actual: str) -> None:
    """
    Record a surprise: agent expected [expected] from [entity], got [actual].
    Surprises automatically spawn a follow-up question node.
    """
    today = date.today().isoformat()
    kg = _kg()

    surprise_desc = f"expected «{expected}» → got «{actual}»"
    kg.add_triple(subject=entity, predicate="_surprise", obj=surprise_desc, valid_from=today)

    kg.add_triple(
        subject=f"surprise_{entity}_{today}",
        predicate="pulls_question",
        obj=f"why did {entity} do «{actual}» instead of «{expected}»?",
        valid_from=today,
    )


def get_expectations(entity: str) -> list[str]:
    """Return active expectations about an entity."""
    kg = _kg()
    rows = kg.query_entity(entity, direction="outgoing") or []
    return [
        r["object"] for r in rows
        if r.get("predicate") == "_expectation" and r.get("current", True)
    ]


# ---------------------------------------------------------------------------
# living_context — main entry point
# ---------------------------------------------------------------------------

def living_context(entities: list[str]) -> str:
    """
    Build a weighted context block for the given entities.
    Returns a string ready to inject into a system prompt.

    Includes: top weighted facts + open tensions + active expectations.
    """
    sections = []

    for entity in entities:
        facts = kg_query_weighted(entity)
        if not facts:
            continue

        lines = [f"◈ {entity}"]

        for f in facts[:5]:
            if f["weight"] > 0.8:
                age = "now"
            elif f["weight"] > 0.4:
                age = "recent"
            else:
                age = "old"
            lines.append(f"  [{age}] {f['subject']} —{f['predicate']}→ {f['object']}")

        tensions = get_tensions(entity)
        if tensions:
            lines.append(f"  ⚡ tension: {' / '.join(tensions[:2])}")

        expectations = get_expectations(entity)
        if expectations:
            lines.append(f"  ◎ expecting: {expectations[0]}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "(context empty)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    usage = """Usage:
  python -m mnemnet.memory query <entity>
  python -m mnemnet.memory add <subject> <predicate> <object>
  python -m mnemnet.memory context <entity1> [entity2 ...]
  python -m mnemnet.memory tensions <entity>"""

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "query" and len(sys.argv) >= 3:
        print(kg_query_summary(sys.argv[2]))
    elif cmd == "add" and len(sys.argv) >= 5:
        result = kg_add_smart(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Added. Tension: {result['tension'] or 'none'}")
    elif cmd == "context" and len(sys.argv) >= 3:
        print(living_context(sys.argv[2:]))
    elif cmd == "tensions" and len(sys.argv) >= 3:
        t = get_tensions(sys.argv[2])
        print("\n".join(t) if t else "no tensions")
    else:
        print(usage)
