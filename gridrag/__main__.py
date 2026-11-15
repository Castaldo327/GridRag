"""Ask GridRag from the command line."""

import argparse

from gridrag import answer
from gridrag.catalog import demo_catalog
from gridrag.records import Answer, State


def _print_result(result: Answer) -> None:
    """Print the answer with query evidence and aggregate usage."""
    print(result["answer"])
    print(f"\nState: {result['state']}")
    if gate := result.get("gate"):
        print(f"Gate: {gate['reason']}")
    if selection := result.get("route"):
        print(f"Schema: {len(selection['tables'])} of {len(demo_catalog().tables)} tables selected")
        print(f"  {', '.join(selection['tables']) or 'No matching tables'}")
    for call in result["tool_calls"]:
        print(f"\nSQL: {call['query']}\n  -> {call['error'] or str(call['rows']) + ' rows'}")
    usage = result["usage"]
    print(f"\n{result['timings']['total']:.2f}s · {usage['calls']} model calls · estimated ${usage['cost_usd']:.5f}")


def _print_diagnostics(result: Answer) -> None:
    """Print detailed retrieval, timing, and provider usage records."""
    gate = result.get("gate")
    selection = result.get("route")
    usage = result["usage"]
    if gate:
        print(f"Gate scores: relevance {gate['relevance']:.2f} · malicious {gate['malicious']:.2f}")
    if selection:
        if metadata := selection.get("metadata_filter"):
            print(
                f"Metadata categories: {', '.join(metadata['selected_tags']) or '(full catalog)'} · "
                f"{len(metadata['candidates'])} candidate tables"
                + (f" · {metadata['fallback']}" if metadata["fallback"] else "")
            )
        print("Table scores:")
        for name, probability in selection["scores"].items():
            print(f"  {name}: {probability:.2f}")
        for table, scores in selection["column_scores"].items():
            print(f"Column scores for {table}:")
            for name, probability in scores.items():
                print(f"  {name}: {probability:.2f}")
    print("Timings:", ", ".join(f"{name} {seconds:.2f}s" for name, seconds in result["timings"].items()))
    print(f"Tokens: {usage['input_tokens']:,} in ({usage['cached_tokens']:,} cached) · {usage['output_tokens']:,} out")
    for call in usage["per_call"]:
        print(
            f"  {call['stage']:<6} {call['kind']:<9} {call['seconds']:.2f}s {call['input_tokens']:>6,} in "
            f"{call['output_tokens']:>5,} out" + (f"  {call['error']}" if call["error"] else "")
        )
    if result["state"] == State.FAILED:
        print(f"Failed during {result.get('stage')}: {result.get('error')}")


def main() -> None:
    """Run a warehouse question with optional routing and usage diagnostics."""
    parser = argparse.ArgumentParser(prog="python -m gridrag", description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--verbose", action="store_true", help="show table/column scores and per-call diagnostics")
    args = parser.parse_args()
    try:
        question = answer.clean_question(args.question)
    except ValueError as exc:
        parser.error(str(exc))
    result = answer.answer(question)

    _print_result(result)
    if args.verbose:
        _print_diagnostics(result)
    if result["state"] in {State.FAILED, State.WRITE_FAILED}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
