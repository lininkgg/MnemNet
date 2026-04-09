"""
memory.py — MnemNet core.

Four mechanisms on top of mempalace KG:
  1. Temporal decay    — recent facts are louder, old ones fade to background
  2. Temperature       — important memories decay slower; trivial ones faster
  3. Auto-tension      — contradictions are held as tension nodes, not overwritten
  4. Predictive layer  — expectations and surprises as first-class facts

Temperature scale:
  0.5  — fleeting, decays faster than normal
  1.0  — default, standard decay
  2.0  — notable, decays 2× slower
  3.0  — significant
  5.0  — core memory, barely decays
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
# Temperature
# ---------------------------------------------------------------------------

_TEMP_PREFIX = "_temp_"

# Auto-temperature rules (applied when no explicit temperature given)
_AUTO_TEMP_TENSION   = 2.0   # fact caused a contradiction
_AUTO_TEMP_SURPRISE  = 2.5   # fact is a surprise
_AUTO_TEMP_EXPECTATION = 1.5 # expectations matter a bit more than plain facts


def _store_temperature(kg: KnowledgeGraph, subject: str, predicate: str, temperature: float) -> None:
    """Store temperature as a metadata node: subject —_temp_<predicate>→ <value>"""
    if temperature == 1.0:
        return  # default — no need to store
    kg.add_triple(
        subject=subject,
        predicate=f"{_TEMP_PREFIX}{predicate}",
        obj=str(temperature),
        valid_from=date.today().isoformat(),
    )


def _get_temperature(kg: KnowledgeGraph, subject: str, predicate: str) -> float:
    """Read stored temperature for a fact. Returns 1.0 if not set."""
    rows = kg.query_entity(subject, direction="outgoing") or []
    for row in rows:
        if row.get("predicate") == f"{_TEMP_PREFIX}{predicate}":
            try:
                return float(row["object"])
            except (ValueError, KeyError):
                pass
    return 1.0


def _auto_temperature(predicate: str, has_tension: bool) -> float:
    """Assign temperature automatically based on fact type."""
    if has_tension:
        return _AUTO_TEMP_TENSION
    if predicate == "_surprise":
        return _AUTO_TEMP_SURPRISE
    if predicate == "_expectation":
        return _AUTO_TEMP_EXPECTATION
    return 1.0


# ---------------------------------------------------------------------------
# Temporal decay
# ---------------------------------------------------------------------------

def _decay_weight(valid_from: str | None, temperature: float = 1.0) -> float:
    """
    Weight a fact by age and temperature.

    temperature > 1.0 → decays slower (important memories last longer)
    temperature < 1.0 → decays faster (fleeting impressions)
    temperature = 1.0 → standard decay (default)

    Returns value in [cfg.decay.floor, 1.0]
    """
    if not valid_from:
        return 0.5
    try:
        created = date.fromisoformat(valid_from[:10])
        days = (date.today() - created).days
        effective_lambda = cfg.decay.lam / max(temperature, 0.1)
        weight = math.exp(-effective_lambda * days)
        return max(weight, cfg.decay.floor)
    except Exception:
        return 0.5


def kg_query_weighted(entity: str) -> list[dict]:
    """
    Query the KG and attach a temporal weight (with temperature) to each fact.
    Returns facts sorted loud → quiet. Temperature metadata nodes are excluded.
    """
    kg = _kg()
    rows = kg.query_entity(entity) or []

    weighted = []
    for row in rows:
        predicate = row.get("predicate", "")
        # Skip temperature metadata nodes
        if predicate.startswith(_TEMP_PREFIX):
            continue
        temperature = _get_temperature(kg, row.get("subject", entity), predicate)
        weight = _decay_weight(row.get("valid_from"), temperature)
        weighted.append({**row, "weight": round(weight, 3), "temperature": temperature})

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
        temp_hint = f" 🌡{f['temperature']}" if f["temperature"] != 1.0 else ""
        lines.append(f"  {bar}{temp_hint} {f['subject']} —{f['predicate']}→ {f['object']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contradiction → tension
# ---------------------------------------------------------------------------

def kg_add_smart(
    subject: str,
    predicate: str,
    obj: str,
    temperature: float | None = None,
) -> dict:
    """
    Add a fact with contradiction detection and temperature support.

    temperature — importance of this memory (default: auto-detected):
        0.5  fleeting     1.0  normal     2.0  notable
        3.0  significant  5.0  core memory

    If [subject → predicate → *something else*] already exists,
    both facts are kept and the conflict is recorded as a tension node.

    Returns: {"added": True, "tension": str | None, "temperature": float}
    """
    today = date.today().isoformat()
    kg = _kg()

    existing = kg.query_entity(subject, direction="outgoing") or []
    tension = None

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

    # Resolve temperature
    has_tension = tension is not None
    if temperature is None:
        temperature = _auto_temperature(predicate, has_tension)
    elif has_tension and temperature < _AUTO_TEMP_TENSION:
        # Tension always bumps temperature to at least 2.0
        temperature = max(temperature, _AUTO_TEMP_TENSION)

    kg.add_triple(subject=subject, predicate=predicate, obj=obj, valid_from=today)
    _store_temperature(kg, subject, predicate, temperature)

    return {"added": True, "tension": tension, "temperature": temperature}


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
    today = date.today().isoformat()
    kg.add_triple(subject=entity, predicate="_expectation", obj=prediction, valid_from=today)
    _store_temperature(kg, entity, "_expectation", _AUTO_TEMP_EXPECTATION)


def add_surprise(entity: str, expected: str, actual: str) -> None:
    """
    Record a surprise: agent expected [expected] from [entity], got [actual].
    Surprises automatically spawn a follow-up question node and get high temperature.
    """
    today = date.today().isoformat()
    kg = _kg()

    surprise_desc = f"expected «{expected}» → got «{actual}»"
    kg.add_triple(subject=entity, predicate="_surprise", obj=surprise_desc, valid_from=today)
    _store_temperature(kg, entity, "_surprise", _AUTO_TEMP_SURPRISE)

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

    Includes: top weighted facts (with temperature) + open tensions + active expectations.
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
            temp = f["temperature"]
            temp_hint = f" temp:{temp}" if temp != 1.0 else ""
            lines.append(f"  [{age}{temp_hint}] {f['subject']} —{f['predicate']}→ {f['object']}")

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
    usage = """Usage:
  python -m mnemnet.memory query <entity>
  python -m mnemnet.memory add <subject> <predicate> <object> [temperature]
  python -m mnemnet.memory context <entity1> [entity2 ...]
  python -m mnemnet.memory tensions <entity>"""

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "query" and len(sys.argv) >= 3:
        print(kg_query_summary(sys.argv[2]))
    elif cmd == "add" and len(sys.argv) >= 5:
        temp = float(sys.argv[5]) if len(sys.argv) >= 6 else None
        result = kg_add_smart(sys.argv[2], sys.argv[3], sys.argv[4], temperature=temp)
        print(f"Added. Temperature: {result['temperature']}. Tension: {result['tension'] or 'none'}")
    elif cmd == "context" and len(sys.argv) >= 3:
        print(living_context(sys.argv[2:]))
    elif cmd == "tensions" and len(sys.argv) >= 3:
        t = get_tensions(sys.argv[2])
        print("\n".join(t) if t else "no tensions")
    else:
        print(usage)
