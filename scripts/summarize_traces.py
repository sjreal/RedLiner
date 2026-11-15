"""Summarize local graph spans into a small performance/cost report."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List


def summarize(path: Path) -> str:
    node_durations: Dict[str, List[float]] = defaultdict(list)
    llm_costs: List[float] = []
    llm_calls = 0
    trace_ids = set()
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event: Dict[str, Any] = json.loads(line)
        if event.get("trace_id"):
            trace_ids.add(event["trace_id"])
        if event.get("event") == "node_finished" and event.get("duration_ms") is not None:
            node_durations[event["node"]].append(float(event["duration_ms"]))
        if event.get("event") == "llm_generation":
            llm_calls += 1
            cost = event.get("usage", {}).get("cost_usd")
            if isinstance(cost, (int, float)) and math.isfinite(cost):
                llm_costs.append(float(cost))

    rows = [
        "# RedLiner run evaluation",
        "",
        f"- Deals traced: **{len(trace_ids)}**",
        f"- LLM calls observed: **{llm_calls}**",
        f"- Reported LLM cost: **${sum(llm_costs):.6f}** "
        "(only calls where the API returned a cost value)",
        "",
        "| Graph node | Runs | Mean (ms) | p95 (ms) |",
        "|---|---:|---:|---:|",
    ]
    for node, values in sorted(node_durations.items()):
        ordered = sorted(values)
        p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
        rows.append(f"| {node} | {len(values)} | {mean(values):.2f} | {ordered[p95_index]:.2f} |")
    if not node_durations:
        rows.append("| _No completed node spans yet_ | 0 | — | — |")
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "Helpers" / "graph_traces.jsonl",
    )
    parser.add_argument("--output", type=Path, help="Optional Markdown output path")
    args = parser.parse_args()
    report = summarize(args.trace_file)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
