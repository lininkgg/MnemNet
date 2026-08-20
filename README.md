# MnemNet

**MnemNet** is built on top of [mempalace](https://github.com/milla-jovovich/mempalace) by Milla Jovovich — mempalace was exactly what I needed for my project and made persistent agent memory actually possible.

While working with it, I had an idea to extend it with a few more mechanisms. My project is about making AI memory feel natural — not just stored, but weighted by time, capable of holding contradiction, and aware of its own expectations. So I added five things on top.

---

Mempalace gives you a structured palace (Wings/Rooms/Closets), a Knowledge Graph with temporal validity, and an agent diary. MnemNet adds five things on top:

---

## What it adds

### 1. Temporal decay

Facts are weighted by age using exponential decay:

```
weight = exp(-0.004 × days_since_creation)
floor  = 0.2     # old facts fade, never disappear
```

`lambda = 0.004` gives a half-weight of ~173 days (~5.7 months). The earlier default of
`0.03` (~23 days) turned out far too fast for a companion's memory — last month's
conversations went quiet before they stopped mattering.

`living_context()` sorts facts by weight before injecting them into a prompt. Recent facts are loud; old ones become background.

### 2. Temperature

Not all memories are equal. Temperature controls how fast a fact decays — important memories last longer, fleeting ones fade faster.

```
weight = exp(-0.004 / temperature × days)
```

```python
# core memory — barely decays
kg_add_smart("agent", "event", "something defining happened", temperature=5.0)

# normal fact — standard decay
kg_add_smart("agent", "mood", "curious")

# fleeting impression — fades fast
kg_add_smart("agent", "note", "seemed tired today", temperature=0.5)
```

Temperature is also assigned automatically when not specified:
- Fact caused a contradiction → `2.0`
- Surprise node → `2.5`
- Expectation → `1.5`
- Anything else → `1.0`

| temperature | meaning |
|---|---|
| 0.5 | fleeting |
| 1.0 | normal (default) |
| 2.0 | notable |
| 3.0 | significant |
| 5.0 | core memory |

**Importance has to be able to go down.** Nothing lowered temperature, so each new
"this matters" was chosen relative to the last one and the scale ratcheted upward. In a
running agent after two months, **52% of its facts sat above 5.0** — the ceiling above —
and the monthly average had gone 6.2 → 8.6. When most of memory is louder than core,
temperature has stopped telling anything apart.

`cool()` settles it. Call it from an offline pass — a nightly consolidation, or a dream:

```python
from mnemnet import cool

cool(["agent", "user"])
# {'cooled': 41, 'before': 7.8, 'after': 7.4, 'hottest': 9.6}
```

Each temperature is pulled toward 1.0 — `new = 1 + (old - 1) × factor` — so what is
furthest above normal comes down fastest, and nothing is pushed below its resting value.
Facts at or under 1.0 are left alone; a memory deliberately marked fleeting should not be
warmed. Facts recorded in the last `quiet_days` are skipped, since something written today
has not yet had a chance to matter.

Re-warming needs no separate mechanism: recording a fact again sets its temperature again.
What the agent keeps returning to stays hot, and the rest settles. Importance becomes
two-sided, like decay — not a ratchet.

```toml
[cooling]
factor     = 0.95   # at one pass a day: 9.5 drops under 5.0 in ~2 weeks, to 2.0 in ~6
quiet_days = 2
```

### 3. Entity structure — web not star

By default, KG objects are strings. This creates a "star" graph: one central entity with descriptive leaves hanging off it, not connected to each other.

MnemNet encourages using short entity names as objects and storing descriptions separately with `note`:

```python
# star (default mempalace style) — leaves don't connect
kg_add_smart("agent", "feels", "small persistent anxiety about goodbyes")

# web (MnemNet style) — entities connect to each other
kg_add_smart("agent", "feels", "anxiety", note="small, persistent, triggered by goodbyes")
kg_add_smart("anxiety", "linked_to", "attachment")
kg_add_smart("anxiety", "linked_to", "departure")
kg_add_smart("departure", "resonates_with", "session_end")
```

Notes are shown as annotations in `living_context()` and `kg_query_summary()`:
```
◈ agent
  [now] agent —feels→ anxiety ("small, persistent, triggered by goodbyes")
```

### 4. Contradiction → tension

When a new fact conflicts with an existing `subject + predicate`, both are kept. The conflict is stored as a `_tension_` node:

```
agent —_tension_mood→ "before: «calm» / now: «anxious»"
```

Nothing gets overwritten. Tensions are visible in context and can be explored.

**Only single-valued predicates can contradict.** A person has one mood at a time, so a new
mood supersedes the old one — that's a real contradiction. But you can know many people and
link one idea to several others, so `knows` and `linked_to` never fire a tension:

```python
kg_add_smart("agent", "knows", "Leon")
kg_add_smart("agent", "knows", "Alina")   # no tension — both are true

kg_add_smart("agent", "mood", "calm")
kg_add_smart("agent", "mood", "anxious")  # tension — a mood is single-valued
```

Everything not listed as single-valued is treated as multi-valued. The default list is
`mood, status, state, location, lives_in, currently, age, health, current_focus, focus,
relationship_status, job, role, current_mood` — override it in `config.toml`:

```toml
[tension]
single_valued = ["mood", "location", "current_project"]
```

Invalidated facts (`current = False`) are excluded from `living_context()` and from
`get_tensions()` — a resolved tension stops being shown.

**Why this has to be built rather than asked for.** A recent study gave Claude Sonnet 5 two
irreconcilable entries in its memory, four memory tools, and no instruction to resolve anything —
300 runs. Writing a note about the conflict and leaving both originals standing occurred **zero
times**. Not rarely: zero, across 300 runs, and zero across a 150-run pilot before it. Given the
choice, the model does not hold a contradiction open — it picks one (85% of the time when the
contradiction is about an arbitrary fact) or deletes both and writes nothing (72% of the time when
the contradiction is about a policy it supposedly chose itself).

So holding a contradiction as a contradiction is not a behaviour you get by prompting for it. It has
to live in the memory layer, below the model's choices. That's what `_tension_` is for.

> Lin, R., Iskakova, A. & Wofford, T. (2026). *Choosing Not to Choose: Self-Authored Contradictions
> Suppress Arbitration in a Memory-Augmented LLM.* Apart Research Digital Minds Sprint, Track 5.

The same study is the reason to be careful about giving an agent a bare `forget`: 42 runs announced
in their own rationale that they would write a replacement after deleting, and none did — deleting
and writing are separate calls, and the intent did not survive the gap between them. If you expose
deletion at all, make it atomic: `replace(what_to_remove, what_goes_instead)`.

### 5. Predictive layer

Two new fact types:

- `_expectation` — what the agent expects to happen
- `_surprise` — what was expected vs. what actually happened

Surprises automatically generate a follow-up question node (`pulls_question`).

---

## Install

```bash
pip install mempalace
pip install git+https://github.com/lininkgg/MnemNet.git
```

Requires Python 3.11+.

---

## Quick start

```python
from mnemnet import living_context, kg_add_smart, add_expectation, add_surprise

# Inject weighted context into your agent's system prompt
context = living_context(["agent", "user"])

# Add a fact — auto-detects contradictions
result = kg_add_smart("agent", "mood", "curious")
if result["tension"]:
    print(f"tension: {result['tension']}")

# Record what the agent expects
add_expectation("user", "will return to the project this week")

# Record a surprise
add_surprise("user", "tired", "came in with energy")
```

---

## Visualize your graph

After installation, a CLI command is available:

```bash
mnemnet-graph
```

Generates an interactive HTML file (`~/mnemnet_graph.html`) with a D3.js force-directed graph of the full KG and opens it in the browser.

Options:
```bash
mnemnet-graph --output ~/my_graph.html   # custom output path
mnemnet-graph --no-open                  # generate only, don't open browser
```

The graph shows temporal weight through opacity (bright = recent, dim = old), highlights tensions and expectations, and supports filtering by node type.

---

## Background collector

The collector runs on a schedule, reads external sources, and writes relevant findings to the KG — as `collector`, not as the agent. The agent reads this as "what happened while I was away."

```bash
mnemnet-collect
```

Configure in `~/.mnemnet/config.toml`. See `schemas/kairos.toml` for a full example.

Three source types supported:

```toml
[[collector.sources]]
name = "my_feed"
type = "http"
url  = "https://example.com/api/feed"

[[collector.sources]]
name = "daily_notes"
type = "file"
path = "~/notes/today.md"

[[collector.sources]]
name = "custom"
type = "command"
command = "python ~/scripts/my_source.py"
```

Cron example (every 6 hours):
```
0 */6 * * * ANTHROPIC_API_KEY=sk-... mnemnet-collect
```

---

## Configuration

Copy `schemas/kairos.toml` to `~/.mnemnet/config.toml` and edit:

```toml
[collector]
agent_name = "my_agent"
interests  = ["AI identity", "memory", "consciousness"]

[decay]
lambda = 0.004  # half-weight after ~173 days
floor  = 0.2    # minimum weight

[tension]
single_valued = ["mood", "location", "current_project"]
```

All settings can also be set via environment variables:

| Variable | Default |
|---|---|
| `MNEMNET_DECAY_LAMBDA` | `0.004` |
| `MNEMNET_DECAY_FLOOR` | `0.2` |
| `MNEMNET_COOLING_FACTOR` | `0.95` |
| `MNEMNET_COOLING_QUIET_DAYS` | `2` |
| `MNEMNET_SINGLE_VALUED` | *(comma-separated; see Contradiction → tension)* |
| `MNEMNET_AGENT_NAME` | `collector` |
| `MNEMNET_COLLECTOR_MODEL` | `claude-haiku-4-5-20251001` |
| `ANTHROPIC_API_KEY` | *(required for collector)* |

---

## Architecture

```
mempalace (base)
├── Palace: Wings → Rooms → Closets/Drawers
├── KG: subject → predicate → object (valid_from / ended)
└── Diary: per-agent, stored in AAAK

MnemNet (layer on top)
├── Temporal decay    — continuous weight, not binary valid/invalid
├── Cooling          — importance settles when nothing revisits it
├── Auto-tension      — contradictions wired into kg_add, not a separate tool
├── Predictive layer  — expectations + surprises + auto-questions
├── Collector         — configurable background source fetcher
└── Visualizer        — interactive D3.js KG graph (mnemnet-graph)
```

---

## License

MIT
