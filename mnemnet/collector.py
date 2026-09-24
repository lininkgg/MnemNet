"""
collector.py — MnemNet background collector.

Runs on a schedule (cron or manually), reads external sources,
and writes relevant findings to the KG as `collector` — not as the agent.

The agent reads collector output as "what happened while I was away."

Configure sources in ~/.mnemnet/config.toml:

    [collector]
    agent_name   = "my_agent"
    model        = "claude-haiku-4-5-20251001"
    interests    = ["AI identity", "memory", "consciousness"]

    [[collector.sources]]
    name = "my_feed"
    type = "http"
    url  = "https://example.com/api/feed"
    auth_env = "MY_FEED_TOKEN"   # optional: env var with Bearer token

    [[collector.sources]]
    name = "local_notes"
    type = "file"
    path = "~/notes/daily.md"

    [[collector.sources]]
    name = "custom_script"
    type = "command"
    command = "python ~/my_source.py"
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

import anthropic
from mempalace.knowledge_graph import KnowledgeGraph

from . import config as cfg


TODAY = datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Source fetchers
# ---------------------------------------------------------------------------

def _fetch_http(source: dict) -> str:
    url = source.get("url", "")
    if not url:
        return ""

    headers = []
    auth_env = source.get("auth_env")
    if auth_env:
        token = os.environ.get(auth_env, "")
        if token:
            headers = ["-H", f"Authorization: Bearer {token}"]

    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "15"] + headers + [url],
            capture_output=True, text=True, timeout=20,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _fetch_file(source: dict) -> str:
    path = Path(source.get("path", "")).expanduser()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _fetch_command(source: dict) -> str:
    cmd = source.get("command", "")
    if not cmd:
        return ""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def fetch_source(source: dict) -> str:
    """Dispatch to the right fetcher based on source type."""
    stype = source.get("type", "")
    name = source.get("name", stype)

    if stype == "http":
        content = _fetch_http(source)
    elif stype == "file":
        content = _fetch_file(source)
    elif stype == "command":
        content = _fetch_command(source)
    else:
        print(f"  [{name}] unknown source type: {stype!r}")
        return ""

    if content:
        print(f"  [{name}] fetched {len(content)} chars")
    else:
        print(f"  [{name}] empty or failed")

    return content


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _build_interests_str() -> str:
    interests = cfg.collector.interests
    if not interests:
        return "general knowledge, recent events, anything notable"
    return ", ".join(interests)


def analyze_and_store(api_key: str, source_name: str, raw_content: str) -> int:
    """
    Send raw content to Claude Haiku. It picks relevant facts and stores them in the KG.
    Returns number of facts stored.
    """
    if not raw_content.strip():
        return 0

    client = anthropic.Anthropic(api_key=api_key)
    interests = _build_interests_str()

    prompt = f"""You are analyzing content from source "{source_name}" for an AI agent.
The agent is interested in: {interests}

From the content below, extract at most 3 facts that are genuinely relevant to the agent's interests.
For each fact, return a JSON object:
{{"subject": "...", "predicate": "published_on_{source_name}", "object": "brief description"}}

If nothing is relevant, return an empty list [].
Reply with a JSON array only, no explanation.

Content:
{raw_content[:3000]}"""

    try:
        response = client.messages.create(
            model=cfg.collector.model,
            max_tokens=cfg.collector.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        facts = json.loads(response.content[0].text.strip())
    except Exception as e:
        print(f"  analysis error: {e}")
        return 0

    if not facts:
        return 0

    kg = KnowledgeGraph()
    today = datetime.now().strftime("%Y-%m-%d")
    for f in facts:
        kg.add_triple(
            subject=f["subject"],
            predicate=f["predicate"],
            obj=f["object"],
            valid_from=today,
        )
        print(f"  + {f['subject']} → {str(f['object'])[:60]}")

    return len(facts)


# ---------------------------------------------------------------------------
# Diary
# ---------------------------------------------------------------------------

def _write_diary(total_facts: int) -> None:
    try:
        from mempalace.mcp_server import tool_diary_write
        tool_diary_write(
            agent_name=cfg.collector.agent_name,
            entry=f"SESSION:{TODAY}|collector.run|facts_added:{total_facts}",
            topic="external events",
        )
    except Exception:
        pass  # diary is optional


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(api_key: str | None = None) -> None:
    """Run the collector: fetch all sources, analyze, store in KG."""
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    sources = cfg._toml.get("collector", {}).get("sources", [])
    if not sources:
        print("No sources configured. Add [[collector.sources]] to ~/.mnemnet/config.toml")
        sys.exit(0)

    print(f"[{TODAY}] collector started — {len(sources)} source(s)")

    total = 0
    for source in sources:
        name = source.get("name", "unnamed")
        print(f"\n  fetching: {name}")
        content = fetch_source(source)
        count = analyze_and_store(api_key, name, content)
        total += count

    _write_diary(total)
    print(f"\n  done. {total} fact(s) added.")


def main():
    run()


if __name__ == "__main__":
    main()
