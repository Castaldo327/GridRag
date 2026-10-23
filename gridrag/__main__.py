"""Ask Grid History from the command line."""

import argparse

from gridrag import answer


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m gridrag", description=__doc__)
    parser.add_argument("question")
    args = parser.parse_args()
    res = answer.answer(args.question)
    print(f"state: {res['state']}")
    print(res["answer"])
    for c in res["tool_calls"]:
        print(f"  run_sql: {c['query']}\n    -> {c['error'] or str(c['rows']) + ' rows'}")


if __name__ == "__main__":
    main()
