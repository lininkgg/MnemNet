"""
Allow running MnemNet as: python -m mnemnet <command>

Commands:
  query <entity>                   — weighted facts for an entity
  add <subject> <predicate> <obj>  — add a fact (with contradiction detection)
  context <entity1> [entity2 ...]  — full living context block
  tensions <entity>                — open tensions for an entity
  graph [--output path] [--no-open] — generate interactive KG graph
  collect                          — run background collector
"""

import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd in ("query", "add", "context", "tensions"):
        from .memory import kg_query_summary, kg_add_smart, living_context, get_tensions

        if cmd == "query" and len(sys.argv) >= 3:
            print(kg_query_summary(sys.argv[2]))
        elif cmd == "add" and len(sys.argv) >= 5:
            result = kg_add_smart(sys.argv[2], sys.argv[3], sys.argv[4])
            print(f"Added. Tension: {result['tension'] or 'none'}")
        elif cmd == "context" and len(sys.argv) >= 3:
            print(living_context(sys.argv[2:]))
        elif cmd == "tensions" and len(sys.argv) >= 3:
            t = get_tensions(sys.argv[2])
            print("\n".join(t) if t else "no tensions")
        else:
            print(__doc__.strip())

    elif cmd == "graph":
        from .visualize import main as graph_main
        sys.argv = sys.argv[1:]  # shift so argparse sees --output etc.
        graph_main()

    elif cmd == "collect":
        from .collector import main as collect_main
        collect_main()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__.strip())
        sys.exit(1)


main()
