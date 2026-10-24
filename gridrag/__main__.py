"""Ask GridRag from the command line."""

import argparse

from gridrag import answer
from gridrag.catalog import demo_catalog
from gridrag.records import State


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m gridrag", description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--verbose", action="store_true", help="show routing scores and per-call diagnostics")
    args = parser.parse_args()
    try:
        question = answer.clean_question(args.question)
    except ValueError as exc:
        parser.error(str(exc))
    res = answer.answer(question)

    print(res["answer"])
    print(f"\nState: {res['state']}")
    if g := res.get("gate"):
        print(f"Gate: {g['reason']}")
    if r := res.get("route"):
        print(f"Schema: {len(r['tables'])} of {len(demo_catalog().tables)} tables selected"
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
            for heading, scores in (("Routing scores:", r["scores"]), ("ISO scores:", r["iso_scores"])):
                print(heading)
                for name, probability in scores.items():
                    score = "?" if probability is None else f"{probability:.2f}"
                    print(f"  {name}: {score}")
        print("Timings:", ", ".join(f"{name} {s:.2f}s" for name, s in res["timings"].items()))
        print(f"Tokens: {u['input_tokens']:,} in ({u['cached_tokens']:,} cached) · {u['output_tokens']:,} out")
        for call in u["per_call"]:
            print(f"  {call['stage']:<6} {call['kind']:<9} {call['seconds']:.2f}s {call['input_tokens']:>6,} in "
                  f"{call['output_tokens']:>5,} out" + (f"  {call['error']}" if call["error"] else ""))
        if res["state"] == State.FAILED:
            print(f"Failed during {res.get('stage')}: {res.get('error')}")
    if res["state"] in {State.FAILED, State.WRITE_FAILED}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
