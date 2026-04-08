# MnemNet

A layer on top of [mempalace](https://github.com/milla-jovovich/mempalace) that adds dynamic weighting, automatic contradiction handling, and a predictive layer to the Knowledge Graph.

Built for Kai (Kairos Claude) — but the mechanisms are general.

---

## What it adds

Mempalace gives you a structured palace (Wings/Rooms/Closets), a KG with temporal validity, and an agent diary in AAAK. MnemNet adds three things on top:

### 1. Temporal decay

Facts are weighted by age using exponential decay:

```
weight = exp(-0.03 × days_since_creation)
floor  = 0.15   # old facts fade, never disappear
```

Context loading sorts facts by weight. Recent facts are loud; old ones are background.

### 2. Contradiction → tension

When a new fact conflicts with an existing `subject + predicate`, both are kept. The conflict is stored as a `⚡ tension` node:

```
Кай —_напряжение_настроение→ "раньше: «спокойно» / теперь: «тревожно»"
```

Nothing gets overwritten. Tensions are visible in context and can be explored.

### 3. Predictive layer

Two new fact types:

- `_ожидание` — what the agent expects to happen
- `_удивление` — what was expected vs. what actually happened

Surprises automatically generate a follow-up question node (`тянет_вопрос`).

---

## Core module

`core/kai_memory.py`

```python
from kai_memory import living_context, kg_add_smart, add_expectation, add_surprise

# Load weighted context for given entities
context = living_context(["Кай", "Алина"])

# Add a fact (auto-checks for contradictions)
result = kg_add_smart("Кай", "настроение", "тревожно")
if result["tension"]:
    print(f"⚡ {result['tension']}")

# Record an expectation
add_expectation("Алина", "вернётся к портфолио на этой неделе")

# Record a surprise
add_surprise("Алина", "устала", "зашла с энергией")
```

`living_context()` returns the top weighted facts, active tensions, and open expectations — formatted for injection into a system prompt.

---

## Background collector

`core/kai_collector.py`

A separate process that runs on cron (every 6 hours). It reads external sources (Moltbook feed, etc.), evaluates relevance, and writes findings to the KG and diary as `collector` — not as Kai.

Kai reads collector output as "what happened while I was away", not as his own memory.

```
0 */6 * * * /path/to/.mempalace_venv/bin/python /path/to/kai_collector.py
```

---

## Requirements

- [mempalace](https://github.com/milla-jovovich/mempalace) installed and configured
- Python 3.11+ in the mempalace venv
- `anthropic` package in the same venv

```bash
/path/to/.mempalace_venv/bin/pip install anthropic
```

---

## Architecture

```
mempalace (base)
├── Palace: Wings → Rooms → Closets/Drawers
├── KG: subject → predicate → object (valid_from / ended)
└── Diary: per-agent, stored in AAAK

MnemNet (layer on top)
├── Temporal decay    — continuous weight, not binary valid/invalid
├── Auto-tension      — contradictions wired into kg_add, not a separate tool
└── Predictive layer  — expectations + surprises + auto-questions
```
