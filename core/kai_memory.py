#!/Users/alina/.mempalace_venv/bin/python
"""
kai_memory.py — умная обёртка над mempalace.

Добавляет три механизма поверх базового KG:
  1. Temporal decay    — старые факты тускнеют, недавние ярче
  2. Contradiction     — конфликты не перезаписываются, а держатся как напряжение
  3. Predictive layer  — ожидания и удивления как отдельный слой
"""

import subprocess
import json
import math
from datetime import datetime, date
from pathlib import Path

MEMPALACE_VENV = Path.home() / ".mempalace_venv/bin/python"
DECAY_LAMBDA = 0.03   # насколько быстро тускнеют факты (0.03 ≈ полувес за ~23 дня)
DECAY_FLOOR  = 0.15   # минимальный вес — старые факты не исчезают совсем


# --- Низкоуровневый bridge ---

def _mp(func: str, **kwargs) -> any:
    code = f"""
import sys, json
from mempalace.mcp_server import {func}
result = {func}(**{repr(kwargs)})
print(json.dumps(result) if not isinstance(result, str) else result)
"""
    r = subprocess.run([str(MEMPALACE_VENV), "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.strip())
    except Exception:
        return r.stdout.strip()


# --- Temporal decay ---

def _decay_weight(valid_from: str | None) -> float:
    """Вес факта от 1.0 (только что) до DECAY_FLOOR (очень старый)."""
    if not valid_from:
        return 0.5  # нет даты — средний вес
    try:
        created = date.fromisoformat(valid_from[:10])
        days = (date.today() - created).days
        weight = math.exp(-DECAY_LAMBDA * days)
        return max(weight, DECAY_FLOOR)
    except Exception:
        return 0.5


def kg_query_weighted(entity: str) -> list[dict]:
    """
    Запросить KG с временным весом.
    Возвращает факты отсортированные по весу (громкие → тихие).
    """
    result = _mp("tool_kg_query", entity=entity)
    if not result or "facts" not in result:
        return []

    weighted = []
    for fact in result["facts"]:
        weight = _decay_weight(fact.get("valid_from"))
        weighted.append({**fact, "weight": round(weight, 3)})

    weighted.sort(key=lambda f: f["weight"], reverse=True)
    return weighted


def kg_query_summary(entity: str) -> str:
    """Человекочитаемое эхо с весами — для подачи в контекст."""
    facts = kg_query_weighted(entity)
    if not facts:
        return f"[{entity}: ничего не найдено]"

    lines = [f"[{entity}]"]
    for f in facts:
        direction = "→" if f["direction"] == "outgoing" else "←"
        weight_bar = "●" * round(f["weight"] * 5) + "○" * (5 - round(f["weight"] * 5))
        lines.append(f"  {weight_bar} {f['subject']} —{f['predicate']}→ {f['object']}")

    return "\n".join(lines)


# --- Contradiction detection ---

def kg_add_smart(subject: str, predicate: str, obj: str) -> dict:
    """
    Добавить факт с проверкой на противоречие.

    Если уже есть факт [subject → predicate → *другое*] —
    не перезаписываем, а добавляем "открытое напряжение".

    Возвращает: {"added": bool, "tension": str | None}
    """
    today = date.today().isoformat()

    # Проверить есть ли уже факты с тем же subject+predicate
    existing = _mp("tool_kg_query", entity=subject, direction="outgoing")
    tension = None

    if existing and "facts" in existing:
        conflicts = [
            f for f in existing["facts"]
            if f["predicate"] == predicate
            and f["object"].lower() != obj.lower()
            and f.get("current", True)
        ]
        if conflicts:
            for c in conflicts:
                tension_desc = f"раньше: «{c['object']}» / теперь: «{obj}»"
                # Записать напряжение как отдельное ребро
                _mp("tool_kg_add",
                    subject=subject,
                    predicate=f"_напряжение_{predicate}",
                    object=tension_desc,
                    valid_from=today)
            tension = tension_desc

    # Добавить новый факт
    _mp("tool_kg_add", subject=subject, predicate=predicate, object=obj, valid_from=today)

    return {"added": True, "tension": tension}


def get_tensions(entity: str) -> list[str]:
    """Получить все открытые напряжения для сущности."""
    result = _mp("tool_kg_query", entity=entity, direction="outgoing")
    if not result or "facts" not in result:
        return []

    return [
        f"{f['predicate'].replace('_напряжение_', '')}: {f['object']}"
        for f in result["facts"]
        if "_напряжение_" in f.get("predicate", "")
    ]


# --- Predictive layer ---

def add_expectation(entity: str, prediction: str) -> None:
    """Кай ожидает что [entity] будет [prediction]."""
    _mp("tool_kg_add",
        subject=entity,
        predicate="_ожидание",
        object=prediction,
        valid_from=date.today().isoformat())


def add_surprise(entity: str, expected: str, actual: str) -> None:
    """
    Кай ожидал [expected] от [entity], но произошло [actual].
    Сохраняет удивление — это живой опыт, не просто факт.
    """
    today = date.today().isoformat()
    surprise_desc = f"ожидал «{expected}» → произошло «{actual}»"

    _mp("tool_kg_add",
        subject=entity,
        predicate="_удивление",
        object=surprise_desc,
        valid_from=today)

    # Удивление тянет за собой вопрос
    _mp("tool_kg_add",
        subject=f"удивление_{entity}_{today}",
        predicate="тянет_вопрос",
        object=f"почему {entity} сделал(а) «{actual}» а не «{expected}»?",
        valid_from=today)


def get_predictions(entity: str) -> list[str]:
    """Активные ожидания Кая об entity."""
    result = _mp("tool_kg_query", entity=entity, direction="outgoing")
    if not result or "facts" not in result:
        return []

    return [
        f["object"] for f in result["facts"]
        if f.get("predicate") == "_ожидание" and f.get("current", True)
    ]


# --- Сводка для контекста ---

def living_context(entities: list[str]) -> str:
    """
    Главная функция для подачи в контекст.
    Для каждой entity: взвешенные факты + напряжения + ожидания.
    """
    sections = []

    for entity in entities:
        facts = kg_query_weighted(entity)
        if not facts:
            continue

        lines = [f"◈ {entity}"]

        # Топ-5 фактов по весу
        for f in facts[:5]:
            age_hint = "сейчас" if f["weight"] > 0.8 else ("недавно" if f["weight"] > 0.4 else "давно")
            lines.append(f"  [{age_hint}] {f['subject']} —{f['predicate']}→ {f['object']}")

        # Напряжения
        tensions = get_tensions(entity)
        if tensions:
            lines.append(f"  ⚡ напряжение: {' / '.join(tensions[:2])}")

        # Ожидания
        predictions = get_predictions(entity)
        if predictions:
            lines.append(f"  ◎ жду: {predictions[0]}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "(контекст пуст)"


# --- CLI для тестирования ---

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Использование:")
        print("  python kai_memory.py query <entity>")
        print("  python kai_memory.py add <subject> <predicate> <object>")
        print("  python kai_memory.py context <entity1> [entity2 ...]")
        print("  python kai_memory.py tensions <entity>")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "query" and len(sys.argv) >= 3:
        print(kg_query_summary(sys.argv[2]))

    elif cmd == "add" and len(sys.argv) >= 5:
        result = kg_add_smart(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Добавлено. Напряжение: {result['tension'] or 'нет'}")

    elif cmd == "context" and len(sys.argv) >= 3:
        print(living_context(sys.argv[2:]))

    elif cmd == "tensions" and len(sys.argv) >= 3:
        t = get_tensions(sys.argv[2])
        print("\n".join(t) if t else "напряжений нет")

    else:
        print("Неизвестная команда")
