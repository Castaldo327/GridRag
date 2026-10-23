"""Ask GridRag from the command line."""

import argparse

from gridrag import answer


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m gridrag", description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--verbose", action="store_true", help="show routing scores and per-call diagnostics")
    args = parser.parse_args()
    res = answer.answer(args.question)

    print(res["answer"])
    print(f"\nState: {res['state']}")
    if g := res.get("gate"):
        print(f"Gate: {g['reason']}")
    if r := res.get("route"):
        print(f"Schema: {len(r['tables'])} of {len(r['table_probabilities'])} tables selected"
              + (" (includes uncertain matches)" if r["fallback"] else ""))
        print(f"  {', '.join(r['tables']) or 'No matching tables'}")
    for c in res["tool_calls"]:
        print(f"\nSQL: {c['query']}\n  -> {c['error'] or str(c['rows']) + ' rows'}")
    u = res["usage"]
    print(f"\n{res['timings']['total']:.2f}s · {u['calls']} model calls · estimated ${u['cost_usd']:.5f}")

    if args.verbose:
        if g:
            print(f"Gate scores: relevance {g['relevance']:.2f} · malicious {g['malicious']:.2f}")
        if r:
            print("Routing scores:")
            for table, probability in r["table_probabilities"].items():
                score = "?" if probability is None else f"{probability:.2f}"
                print(f"  {table}: {score}")
        print("Timings:", ", ".join(f"{name} {s:.2f}s" for name, s in res["timings"].items()))
        print(f"Tokens: {u['input_tokens']:,} in ({u['cached_tokens']:,} cached) · {u['output_tokens']:,} out")
        for c in u["per_call"]:
            print(f"  {c['stage']:<6} {c['kind']:<9} {c['seconds']:.2f}s {c['input_tokens']:>6,} in "
                  f"{c['output_tokens']:>5,} out" + (f"  {c['error']}" if c["error"] else ""))
        if res["state"] == "failed":
            print(f"Failed during {res['stage']}: {res['error']}")
    if res["state"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
