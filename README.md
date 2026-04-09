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
weight = exp(-0.03 × days_since_creation)
floor  = 0.15   # old facts fade, never disappear
```

`living_context()` sorts facts by weight before injecting them into a prompt. Recent facts are loud; old ones become background.

### 2. Temperature

Not all memories are equal. Temperature controls how fast a fact decays — important memories last longer, fleeting ones fade faster.

```
weight = exp(-0.03 / temperature × days)
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
lambda = 0.03   # half-weight after ~23 days
floor  = 0.15   # minimum weight
```

All settings can also be set via environment variables:

| Variable | Default |
|---|---|
| `MNEMNET_DECAY_LAMBDA` | `0.03` |
| `MNEMNET_DECAY_FLOOR` | `0.15` |
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
├── Auto-tension      — contradictions wired into kg_add, not a separate tool
├── Predictive layer  — expectations + surprises + auto-questions
├── Collector         — configurable background source fetcher
└── Visualizer        — interactive D3.js KG graph (mnemnet-graph)
```

---

## License

MIT
