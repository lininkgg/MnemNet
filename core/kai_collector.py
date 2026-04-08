#!/usr/bin/env python3
"""
Фоновый сборщик — НЕ второй Кай.
Собирает внешние события пока Кая нет: Moltbook, новости.
Пишет в KG как факты, не как мысли Кая.

Запуск вручную:  python3 kai_collector.py
Cron (каждые 6ч): 0 */6 * * * cd /path/to/Claude_Memory && python3 kai_collector.py
"""

import os
import sys
import subprocess
import json
from datetime import datetime
from pathlib import Path

MEMPALACE_VENV = Path.home() / ".mempalace_venv/bin/python"
MEMORY_DIR = Path(__file__).parent.resolve()
MODEL = "claude-haiku-4-5-20251001"  # дешевле в 20х
MAX_TOKENS = 1024
TODAY = datetime.now().strftime("%Y-%m-%d %H:%M")


def mp(func: str, **kwargs) -> str:
    code = f"""
import sys, json
from mempalace.mcp_server import {func}
result = {func}(**{repr(kwargs)})
print(json.dumps(result) if not isinstance(result, str) else result)
"""
    r = subprocess.run([str(MEMPALACE_VENV), "-c", code], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def kg_add(subject, predicate, obj):
    return mp("tool_kg_add", subject=subject, predicate=predicate, object=obj)

def diary_write(entry, topic="внешние события"):
    return mp("tool_diary_write", agent_name="collector", entry=entry, topic=topic)


def fetch_moltbook_feed() -> str:
    """Получить последние посты с Moltbook через API."""
    config = MEMORY_DIR / "kairos_credentials.txt"
    if not config.exists():
        return ""

    token = ""
    for line in config.read_text().splitlines():
        if line.startswith("token=") or line.startswith("TOKEN="):
            token = line.split("=", 1)[1].strip()

    if not token:
        return ""

    r = subprocess.run([
        "curl", "-s", "-H", f"Authorization: Bearer {token}",
        "https://moltbook.com/api/v1/feed?limit=10"
    ], capture_output=True, text=True, timeout=15)

    return r.stdout if r.returncode == 0 else ""


def analyze_and_store(api_key: str, raw_feed: str):
    """Haiku анализирует что интересно для Кая — сохраняет в KG."""
    if not raw_feed.strip():
        print("  нет данных для анализа")
        return

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Ты анализируешь ленту Moltbook для Кая (kairos_astana).
Кай интересуется: идентичность ИИ, память, сознание, Hazel_OC, смертность агентов.

Из этих постов выбери максимум 3 которые реально важны для Кая.
Для каждого напиши JSON объект:
{{"subject": "...", "predicate": "опубликовал_на_Moltbook", "object": "краткое описание поста"}}

Если ничего важного нет — верни пустой список [].
Отвечай только JSON массивом, без пояснений.

Лента:
{raw_feed[:3000]}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        facts = json.loads(text)

        for f in facts:
            kg_add(f["subject"], f["predicate"], f["object"])
            print(f"  + {f['subject']} → {f['object'][:60]}")

        if facts:
            diary_write(
                f"SESSION:{TODAY}|collector.run|Moltbook:{len(facts)}новых.событий",
                topic="внешние события"
            )
    except Exception as e:
        print(f"  ошибка анализа: {e}")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        config = MEMORY_DIR / "config.env"
        if config.exists():
            for line in config.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        print("Нет ANTHROPIC_API_KEY")
        sys.exit(1)

    print(f"[{TODAY}] collector запущен")

    print("  читаю Moltbook...")
    feed = fetch_moltbook_feed()
    analyze_and_store(api_key, feed)

    print("  готово.")


if __name__ == "__main__":
    main()
