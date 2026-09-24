"""
memory.py — MnemNet core.

Four mechanisms on top of mempalace KG:
  1. Temporal decay    — recent facts are louder, old ones fade to background
  2. Temperature       — important memories decay slower; trivial ones faster
  3. Auto-tension      — contradictions are held as tension nodes, not overwritten
                         (only for single-valued predicates; multi-valued ones
                         like knows / read_diary_of / linked_to coexist)
  4. Predictive layer  — expectations and surprises as first-class facts

Entity structure:
  Use short entity names as objects, store descriptions separately with `note`:

    kg_add_smart("agent", "feels", "anxiety", note="small but present, triggered by goodbyes")
    kg_add_smart("anxiety", "linked_to", "attachment")   # cross-link → web not star

  This creates a graph where entities connect to each other,
  not a star of descriptive strings hanging off one central node.

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
_NOTE_PREFIX = "_note"   # entity → _note → "description"
_CORR_PREFIX = "_corrected_"
_SRC_PREFIX = "_src_"    # subject → _src_<predicate> → "perceived" | "told" | "inferred" | "wanted"
_REVIEW_PREFIX = "_reviewed_pair"   # subject → _reviewed_pair → "<pair hash>_<verdict>"

# Everything MnemNet writes about a fact rather than as one. Listed once: the weighted
# view used to skip four of these by name and let the rest through, so a tension or an
# expectation showed up twice in the living context — once in its own line, and once
# as an ordinary fact taking one of the five loudest slots.
_INTERNAL_PREFIXES = (_TEMP_PREFIX, _SRC_PREFIX, _CORR_PREFIX, "_tension_", _REVIEW_PREFIX,
                      "_expectation", "_surprise")


def _is_internal(predicate: str) -> bool:
    return predicate.startswith(_INTERNAL_PREFIXES) or predicate == _NOTE_PREFIX

# Where a fact came from. The distinction that matters is the last one: an agent
# writing down what it would like to be true, in the same shape as what it saw.
# That is not hypothetical — a running agent invented a housemate from two empty
# placeholder files, recorded it, and the graph handed the invention back as a loud
# fact on the next waking. Memory with no correction does not fix an error, it
# entrenches it.
SOURCES = {
    "perceived": "I witnessed this — it happened in front of me",
    "told":      "someone told me; I did not witness it",
    "inferred":  "I worked this out; it was not stated",
    "wanted":    "I would like this to be true",
}

# Auto-temperature rules (applied when no explicit temperature given)
_AUTO_TEMP_TENSION   = 2.0   # fact caused a contradiction
_AUTO_TEMP_SURPRISE  = 2.5   # fact is a surprise
_AUTO_TEMP_EXPECTATION = 1.5 # expectations matter a bit more than plain facts


def _store_source(kg: KnowledgeGraph, subject: str, predicate: str, source: str) -> None:
    """Record where a fact came from, beside the fact."""
    if not source:
        return
    kg.add_triple(subject=subject, predicate=f"{_SRC_PREFIX}{predicate}",
                  obj=str(source), valid_from=date.today().isoformat())


def get_source(subject: str, predicate: str) -> str | None:
    """Where a fact came from, or None if it was recorded before anyone asked."""
    kg = _kg()
    rows = kg.query_entity(subject, direction="outgoing") or []
    best, best_date = None, ""
    for row in rows:
        if row.get("predicate") != f"{_SRC_PREFIX}{predicate}" or not row.get("current", True):
            continue
        when = row.get("valid_from") or ""
        if best is None or when >= best_date:
            best, best_date = row.get("object"), when
    return best


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
    """Read stored temperature for a fact. Returns 1.0 if not set.

    Takes the newest still-current record. Cooling supersedes a temperature rather
    than editing it, so several may exist for one fact — reading whichever came back
    first would make cooling look like it had done nothing.
    """
    rows = kg.query_entity(subject, direction="outgoing") or []
    best, best_date = None, ""
    for row in rows:
        if row.get("predicate") != f"{_TEMP_PREFIX}{predicate}" or not row.get("current", True):
            continue
        when = row.get("valid_from") or ""
        if best is None or when >= best_date:
            try:
                best, best_date = float(row["object"]), when
            except (ValueError, KeyError):
                pass
    return 1.0 if best is None else best


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
# Cooling — importance that can go down
# ---------------------------------------------------------------------------

def cool(entities: list[str], factor: float | None = None, quiet_days: int | None = None) -> dict:
    """Let importance fade the way age already does.

    Temperature is set by the agent and nothing lowers it, so each new "this matters"
    is chosen relative to the last one and the scale ratchets upward. Observed in a
    running agent after two months: 52% of its facts sat above 5.0 — the documented
    ceiling for a core memory — and the monthly average had gone 6.2 → 8.6. When most
    of memory is louder than "core", temperature has stopped telling anything apart.

    This pulls each temperature toward 1.0 — `new = 1 + (old - 1) * factor` — so what
    is furthest above normal comes down fastest, and nothing is pushed below its
    resting value. Facts already at or below 1.0 are left alone: a memory deliberately
    marked fleeting should not be warmed.

    Re-warming needs no separate mechanism. Recording a fact again sets its temperature
    again, so what the agent keeps returning to stays hot and the rest settles. Call
    this from an offline pass — consolidation, or a dream.

    quiet_days — only cool facts older than this, so something recorded today is not
    cooled before it has had a chance to matter.

    Returns {"cooled": n, "before": avg, "after": avg, "hottest": value}.
    """
    factor = cfg.cooling.factor if factor is None else factor
    quiet_days = cfg.cooling.quiet_days if quiet_days is None else quiet_days
    kg = _kg()
    today = date.today().isoformat()
    changed, before, after = 0, [], []
    hottest = 0.0

    for entity in entities:
        rows = kg.query_entity(entity, direction="outgoing") or []
        for row in rows:
            pred = row.get("predicate", "")
            if not pred.startswith(_TEMP_PREFIX) or not row.get("current", True):
                continue
            try:
                old = float(row["object"])
            except (ValueError, KeyError, TypeError):
                continue
            if quiet_days:
                try:
                    age = (date.today() - date.fromisoformat((row.get("valid_from") or today)[:10])).days
                    if age < quiet_days:
                        continue
                except Exception:
                    pass
            hottest = max(hottest, old)
            if old <= 1.0:
                continue
            new = round(1.0 + (old - 1.0) * factor, 2)
            if abs(new - old) < 0.01:
                continue
            kg.invalidate(entity, pred, row["object"], ended=today)
            kg.add_triple(subject=entity, predicate=pred, obj=str(new), valid_from=today)
            before.append(old)
            after.append(new)
            changed += 1

    return {"cooled": changed,
            "before": round(sum(before) / len(before), 2) if before else 0.0,
            "after": round(sum(after) / len(after), 2) if after else 0.0,
            "hottest": hottest}


# ---------------------------------------------------------------------------
# Note — entity description
# ---------------------------------------------------------------------------

def set_note(entity: str, note: str) -> None:
    """Attach a human-readable description to an entity node."""
    kg = _kg()
    kg.add_triple(
        subject=entity,
        predicate=_NOTE_PREFIX,
        obj=note,
        valid_from=date.today().isoformat(),
    )


def get_note(entity: str) -> str | None:
    """Return the description attached to an entity, or None."""
    kg = _kg()
    rows = kg.query_entity(entity, direction="outgoing") or []
    for row in rows:
        if row.get("predicate") == _NOTE_PREFIX:
            return row.get("object")
    return None


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
        if _is_internal(predicate):
            continue
        # Skip invalidated / superseded facts — they are no longer true
        if not row.get("current", True):
            continue
        temperature = _get_temperature(kg, row.get("subject", entity), predicate)
        weight = _decay_weight(row.get("valid_from"), temperature)
        weighted.append({**row, "weight": round(weight, 3), "temperature": temperature,
                         "source": get_source(row.get("subject", entity), predicate)})

    weighted.sort(key=lambda f: f["weight"], reverse=True)
    return weighted


def kg_query_summary(entity: str) -> str:
    """Human-readable weighted echo — ready to inject into a prompt."""
    facts = kg_query_weighted(entity)
    if not facts:
        return f"[{entity}: nothing found]"

    kg = _kg()
    lines = [f"[{entity}]"]
    for f in facts:
        filled = round(f["weight"] * 5)
        bar = "●" * filled + "○" * (5 - filled)
        temp_hint = f" 🌡{f['temperature']}" if f["temperature"] != 1.0 else ""
        note = get_note(f["object"])
        note_hint = f' ("{note}")' if note else ""
        lines.append(f"  {bar}{temp_hint} {f['subject']} —{f['predicate']}→ {f['object']}{note_hint}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contradiction → tension
# ---------------------------------------------------------------------------

def kg_add_smart(
    subject: str,
    predicate: str,
    obj: str,
    temperature: float | None = None,
    note: str | None = None,
    source: str | None = None,
) -> dict:
    """
    Add a fact with contradiction detection, temperature, and optional note.

    obj should be a short entity name, not a long description:
        kg_add_smart("agent", "feels", "anxiety", note="small but persistent")
        kg_add_smart("anxiety", "linked_to", "attachment")   # cross-link

    note — description stored on the object entity (obj → _note → note).
           Makes obj a proper node in the graph, not a leaf string.

    temperature — how fast this fact decays (default: auto-detected):
        0.5  fleeting     1.0  normal     2.0  notable
        3.0  significant  5.0  core memory

    Returns: {"added": True, "tension": str | None, "temperature": float}
    """
    today = date.today().isoformat()
    kg = _kg()

    tension = None

    # Only single-valued predicates can contradict. Multi-valued ones
    # (knows, read_diary_of, linked_to, …) coexist — no false tension.
    if _is_single_valued(predicate):
        existing = kg.query_entity(subject, direction="outgoing") or []
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
    _store_source(kg, subject, predicate, source)
    if note:
        set_note(obj, note)

    return {"added": True, "tension": tension, "temperature": temperature, "source": source}


def _is_single_valued(predicate: str) -> bool:
    """
    True if this predicate holds at most one current value, so a conflicting
    new value is a real contradiction (→ tension). Multi-valued predicates
    (knows, read_diary_of, linked_to, …) coexist and never fire tension.
    """
    return predicate.strip().lower() in cfg.tension.single_valued


def get_corrections(entity: str) -> list[str]:
    """Corrections this entity has made to its own record, newest first.

    Worth showing. An agent that can see it has fixed itself before is in a different
    position from one for whom every belief has always been true.

    Each reads now → before → because. The record used to hold only "was «…» — why",
    so a correction made when nothing had been recorded read "was «(nothing)» — the user
    corrected me, I misunderstood": an agent took that as the *current* belief being
    the mistake — the opposite of what it had written. Older records are shown in the
    same shape.
    """
    kg = _kg()
    rows = kg.query_entity(entity, direction="outgoing") or []
    current = {}
    for r in rows:
        p = r.get("predicate", "")
        if r.get("current", True) and not _is_internal(p):
            current.setdefault(p, str(r.get("object", "")))
    out = []
    for r in rows:
        p = r.get("predicate", "")
        if not (p.startswith(_CORR_PREFIX) and r.get("current", True)):
            continue
        base = p.replace(_CORR_PREFIX, "")
        what = str(r.get("object", ""))
        if what.startswith("was «(nothing)» — "):
            what = "before: «nothing on record» — because: " + what[len("was «(nothing)» — "):]
        elif what.startswith("was «"):
            head, _, why = what[len("was «"):].partition("» — ")
            what = f"before: «{head}» — because: {why}"
        now = current.get(base)
        shown = (f"{base}: now «{now[:100]}{'…' if len(now) > 100 else ''}» · {what}" if now
                 else f"{base}: {what}")
        out.append((r.get("valid_from") or "", shown))
    return [t for _, t in sorted(out, reverse=True)]


def get_tensions(entity: str) -> list[str]:
    """Return all open tensions for an entity."""
    kg = _kg()
    rows = kg.query_entity(entity, direction="outgoing") or []
    return [
        f"{r['predicate'].replace('_tension_', '')}: {r['object']}"
        for r in rows
        if "_tension_" in r.get("predicate", "")
        and r.get("current", True)   # hide resolved / invalidated tensions
    ]


# ---------------------------------------------------------------------------
# Correction — replacing, never deleting
# ---------------------------------------------------------------------------

def correct(subject: str, predicate: str, new_obj: str,
            source: str = "perceived", note: str | None = None,
            because: str | None = None) -> dict:
    """Supersede what a fact said, in one move.

    Deliberately not a `forget`. Given tools to delete and a contradiction about its
    own past choices, a model clears the record and states an intention to write a
    replacement that the next step erases — measured at 42 announced replacements
    and none delivered, because deleting and writing were two calls with a gap
    between them (Lin, Iskakova & Wofford 2026). One call cannot have that gap.

    Nothing is destroyed. The old value is ended, so it stops being current and
    stops surfacing, but it stays readable in the timeline — a correction should
    leave a record of having been made.
    """
    kg = _kg()
    today = date.today().isoformat()
    rows = kg.query_entity(subject, direction="outgoing") or []
    superseded = []
    for row in rows:
        if row.get("predicate") != predicate or not row.get("current", True):
            continue
        if (row.get("object") or "").lower() == new_obj.lower():
            continue
        kg.invalidate(subject, predicate, row["object"], ended=today)
        superseded.append(row["object"])

    result = kg_add_smart(subject, predicate, new_obj, note=note, source=source)
    result["superseded"] = superseded
    if because:
        kg.add_triple(subject=subject, predicate=f"_corrected_{predicate}",
                      obj=f"before: «{' / '.join(superseded) or 'nothing on record'}» — because: {because}",
                      valid_from=today)
    return result


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


# ---------------------------------------------------------------------------
# Contradictions found by meaning
# ---------------------------------------------------------------------------
#
# kg_add_smart fires a tension when one subject gets the same predicate twice with a
# different value. That is exact, and in practice nearly blind: agents that write
# free-form predicates phrase one per thought. Measured on two long-running agents,
# 80 distinct predicates in 82 facts and 162 in 168 — zero tensions, ever. One of
# them held "the move was a fresh start" and, a day later, "the move was really running
# away", side by side and unseen.
#
# So candidates are found by meaning, and the judgement is left to the agent — best in
# an offline pass such as a dream. A pair may be a real contradiction (held open, not
# resolved), a change of mind (the earlier is ended, and stays readable), or two
# things that sit together. Every verdict is written to the graph, so the same pair
# is not put to the agent twice.

def _pair_hash(subject: str, a: dict, b: dict) -> str:
    import hashlib
    key = subject.lower() + "||" + "||".join(sorted(
        f"{x['predicate']}={x['object']}".lower() for x in (a, b)))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _default_embed(texts: list[str]):
    """Local sentence embeddings — the same model chroma uses. English-trained:
    similarity between facts written in other languages is less reliable."""
    from chromadb.utils import embedding_functions as ef
    return ef.DefaultEmbeddingFunction()(texts)


def _say(f: dict) -> str:
    return f"{f['predicate'].replace('_', ' ')}: {f['object'].replace('_', ' ')}"


def tension_candidates(entities: list[str], n: int | None = None, floor: float | None = None,
                       embed=None) -> list[dict]:
    """Pairs of current facts about the same subject that are close in meaning.

    Returns up to `n` pairs, most similar first, each
    {"subject", "a", "b", "similarity"} with a/b as {"predicate","object","valid_from"}
    and a the older of the two. Pairs already weighed are left out.

    `embed` is any callable from a list of strings to vectors; the default is local.
    """
    import numpy as np
    n = cfg.tension.per_pass if n is None else n
    floor = cfg.tension.similarity_floor if floor is None else floor
    kg = _kg()
    out = []
    for entity in entities:
        rows = kg.query_entity(entity, direction="outgoing") or []
        reviewed = {str(r.get("object", ""))[:12] for r in rows
                    if r.get("predicate") == _REVIEW_PREFIX}
        facts = [{"predicate": r["predicate"], "object": str(r.get("object", "")),
                  "valid_from": r.get("valid_from") or ""}
                 for r in rows
                 if r.get("current", True) and not _is_internal(r.get("predicate", ""))
                 and r.get("object")]
        if len(facts) < 2:
            continue
        v = np.array((embed or _default_embed)([_say(f) for f in facts]), dtype=float)
        v = v / np.linalg.norm(v, axis=1, keepdims=True)
        sims = v @ v.T
        for i in range(len(facts)):
            for j in range(i + 1, len(facts)):
                if sims[i, j] < floor:
                    continue
                a, b = facts[i], facts[j]
                if (a["valid_from"], a["predicate"]) > (b["valid_from"], b["predicate"]):
                    a, b = b, a
                if _pair_hash(entity, a, b) in reviewed:
                    continue
                out.append({"subject": entity, "a": a, "b": b, "similarity": round(float(sims[i, j]), 3)})
    out.sort(key=lambda x: -x["similarity"])
    return out[:n]


def weigh_pair(pair: dict, verdict: str, note: str = "") -> dict:
    """Record a judgement of one candidate pair. Nothing is deleted by any verdict.

    tension — both still hold and cannot both be true; kept open as a _tension_ node
    revised — the later is what the agent thinks now; the earlier is ended, readable
    fine    — they sit together; only the review is recorded
    """
    if verdict not in ("tension", "revised", "fine"):
        raise ValueError("verdict must be 'tension', 'revised' or 'fine'")
    kg = _kg()
    today = date.today().isoformat()
    s, a, b = pair["subject"], pair["a"], pair["b"]
    note = (note or "").strip()
    if verdict == "tension":
        kg.add_triple(subject=s, predicate=f"_tension_{b['predicate']}",
                      obj=f"before: «{_say(a)}» / now: «{_say(b)}»" + (f" — {note}" if note else ""),
                      valid_from=today)
    elif verdict == "revised":
        kg.invalidate(s, a["predicate"], a["object"], ended=today)
        kg.add_triple(subject=s, predicate=f"{_CORR_PREFIX}{a['predicate']}",
                      obj=f"was «{_say(a)}» — replaced by «{_say(b)}»" + (f"; {note}" if note else ""),
                      valid_from=today)
    kg.add_triple(subject=s, predicate=_REVIEW_PREFIX,
                  obj=f"{_pair_hash(s, a, b)}_{verdict}", valid_from=today)
    return {"verdict": verdict, "subject": s}


def reviewed_pairs(entity: str) -> dict:
    """How many pairs have been weighed for this entity, by verdict."""
    rows = _kg().query_entity(entity, direction="outgoing") or []
    out = {"tension": 0, "revised": 0, "fine": 0}
    for r in rows:
        if r.get("predicate") == _REVIEW_PREFIX:
            v = str(r.get("object", "")).rsplit("_", 1)[-1]
            if v in out:
                out[v] += 1
    return out

def living_context(entities: list[str]) -> str:
    """
    Build a weighted context block for the given entities.
    Returns a string ready to inject into a system prompt.

    Includes: top weighted facts (with temperature) + open tensions + active expectations.
    """
    sections = []

    for entity in entities:
        facts = kg_query_weighted(entity)
        corrections = get_corrections(entity)
        tensions = get_tensions(entity)
        expectations = get_expectations(entity)
        # An entity can matter through a tension or an expectation alone. When those
        # were (wrongly) counted as facts this never came up; now that they are not,
        # skipping on "no facts" would drop them from the context along with it.
        if not (facts or corrections or tensions or expectations):
            continue

        lines = [f"◈ {entity}"]

        # What the agent wished were true is kept, and kept apart. Fed back in the
        # same shape as everything else, a wish is indistinguishable from an
        # observation on the next reading — which is exactly how a confabulation
        # becomes a fact the agent then defends.
        wished = [f for f in facts if f.get("source") == "wanted"]
        facts = [f for f in facts if f.get("source") != "wanted"]

        for f in facts[:5]:
            if f["weight"] > 0.8:
                age = "now"
            elif f["weight"] > 0.4:
                age = "recent"
            else:
                age = "old"
            temp = f["temperature"]
            temp_hint = f" temp:{temp}" if temp != 1.0 else ""
            src = f.get("source")
            src_hint = f" {src}" if src and src != "perceived" else ""
            note = get_note(f["object"])
            note_hint = f' ("{note[:50]}{"…" if len(note) > 50 else ""}")' if note else ""
            lines.append(f"  [{age}{temp_hint}{src_hint}] {f['subject']} —{f['predicate']}→ {f['object']}{note_hint}")

        for f in wished[:2]:
            lines.append(f"  ◇ wished, not observed: {f['subject']} —{f['predicate']}→ {f['object']}")

        for c in corrections[:2]:
            lines.append(f"  ✎ corrected: {c}")

        if tensions:
            lines.append(f"  ⚡ tension: {' / '.join(tensions[:2])}")

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
