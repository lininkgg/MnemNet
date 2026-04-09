# Collector

The collector is a background process that reads external sources and writes relevant findings to the KG — as `collector`, not as your agent. Your agent reads this as "what happened while I was away."

## How it works

1. Reads each configured source (HTTP, file, or command)
2. Sends the content to Claude Haiku with your agent's interests
3. Haiku picks at most 3 relevant facts per source
4. Facts are stored in the KG with today's date
5. A diary entry is written summarizing the run

## Configure sources

In `~/.mnemnet/config.toml`:

### HTTP feed

```toml
[[collector.sources]]
name = "my_feed"
type = "http"
url  = "https://example.com/api/feed?limit=10"
# Optional: env var containing a Bearer token
# auth_env = "MY_FEED_TOKEN"
```

### Local file

```toml
[[collector.sources]]
name = "daily_notes"
type = "file"
path = "~/notes/today.md"
```

### Custom command

Any script or command that prints text to stdout:

```toml
[[collector.sources]]
name   = "rss"
type   = "command"
command = "python ~/scripts/fetch_rss.py"
```

## Interests

The `interests` list in `[collector]` drives relevance filtering.
Be specific — vague interests produce noisy results:

```toml
[collector]
interests = [
  "AI memory and continuity",
  "consciousness research",
  "new papers on cognitive architectures",
]
```

## Running manually

```bash
mnemnet-collect
```

## Cron

```
0 */6 * * * ANTHROPIC_API_KEY=sk-... mnemnet-collect >> ~/mnemnet_collector.log 2>&1
```

## What gets stored

Each fact is stored as a triple:

```
subject —published_on_<source_name>→ brief description
```

The subject is whatever entity Haiku identifies as relevant (a person, project, concept). This keeps collector facts separate from agent-generated facts by predicate pattern.

## Collector vs. agent

The collector writes as `collector` in the diary — not as your agent. This distinction matters: your agent should treat collector output as external observations, not its own memories. It saw these things; it didn't experience them.
