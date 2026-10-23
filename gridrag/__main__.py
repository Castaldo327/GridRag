"""Ask Grid History from the command line."""

import argparse

from gridrag import answer


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m gridrag", description=__doc__)
    parser.add_argument("question")
    args = parser.parse_args()
    res = answer.answer(args.question)
    if g := res.get("gate"):
        print(f"gate: relevance {g['relevance']:.2f} · malicious {g['malicious']:.2f} -> {g['reason']}")
    if r := res.get("route"):
        def scores(probabilities):
            return ", ".join(f"{name} {'?' if p is None else f'{p:.2f}'}" for name, p in probabilities.items())

        print(f"route: {scores(r['probabilities'])}{' (widened: uncertain)' if r['fallback'] else ''}")
        print(f"  tables: {scores(r['table_probabilities'])}")
        print(f"  -> {', '.join(r['tables'])}")
        for table, names in r["columns"].items():
            print(f"     {table}: {', '.join(names)}")
    print(f"state: {res['state']}" + (f" during {res['stage']}: {res['error']}" if res["state"] == "failed" else ""))
    print(res["answer"])
    for c in res["tool_calls"]:
        print(f"  run_sql: {c['query']}\n    -> {c['error'] or str(c['rows']) + ' rows'}")
    u = res["usage"]
    print("timings:", ", ".join(f"{name} {s:.2f}s" for name, s in res["timings"].items()))
    print(f"usage: {u['calls']} calls · {u['input_tokens']:,} in ({u['cached_tokens']:,} cached) · "
          f"{u['output_tokens']:,} out · ${u['cost_usd']:.5f}")
    for c in u["per_call"]:
        print(f"  {c['stage']:<6} {c['kind']:<9} {c['seconds']:.2f}s {c['input_tokens']:>6,} in "
              f"{c['output_tokens']:>5,} out" + (f"  {c['error']}" if c["error"] else ""))
    if res["state"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
