# Getting started

## Prerequisites

- Python 3.11+
- mempalace installed and configured
- An Anthropic API key (for the collector)

## 1. Install mempalace

```bash
pip install mempalace
mempalace init          # creates ~/.mempalace/palace
```

## 2. Install MnemNet

```bash
pip install git+https://github.com/lininkgg/MnemNet.git
```

## 3. Configure

Copy the example config:

```bash
mkdir -p ~/.mnemnet
cp /path/to/MnemNet/schemas/kairos.toml ~/.mnemnet/config.toml
```

Edit `~/.mnemnet/config.toml` — set your agent name, interests, and sources.

## 4. Use in your agent

Add `living_context()` to your system prompt:

```python
import anthropic
from mnemnet import living_context, kg_add_smart

client = anthropic.Anthropic()

def chat(user_message: str, entities: list[str]) -> str:
    context = living_context(entities)

    response = client.messages.create(
        model="claude-opus-4-6",
        system=f"""You are a persistent AI agent with memory.

Current memory context:
{context}

Use this context to maintain continuity across sessions.""",
        messages=[{"role": "user", "content": user_message}],
        max_tokens=1024,
    )
    return response.content[0].text
```

## 5. Add facts

```python
from mnemnet import kg_add_smart, add_expectation, add_surprise, get_tensions

# Add a fact (auto-detects contradictions)
result = kg_add_smart("user", "working_on", "portfolio")
if result["tension"]:
    print(f"Contradiction detected: {result['tension']}")

# Record an expectation
add_expectation("user", "will finish portfolio by Friday")

# Record a surprise
add_surprise("user", "was tired", "came in energized")

# Check open tensions
tensions = get_tensions("user")
```

## 6. Visualize

```bash
mnemnet-graph
```

Opens `~/mnemnet_graph.html` in the browser — an interactive force-directed graph of everything in your KG.

## 7. Run the collector

```bash
ANTHROPIC_API_KEY=sk-... mnemnet-collect
```

Or set up cron to run every 6 hours:
```
0 */6 * * * ANTHROPIC_API_KEY=sk-... mnemnet-collect
```
