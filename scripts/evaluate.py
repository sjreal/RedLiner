"""Reproducible evaluation harness for RedLiner.

Default mode is deterministic (no LLM/OSINT/MCP network calls) so the report is
repeatable. Use --with-llm to measure live model usage/cost for the CrewAI stage.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs"

# Keep the default run reproducible and offline.
os.environ.setdefault("LIVE_OSINT_ENABLED", "false")
os.environ.setdefault("MCP_ENABLED", "false")
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
os.environ.setdefault("REVIEWER_EMAIL", "")
os.environ.setdefault("REVIEWER_WEBHOOK_URL", "")


CLAUSE_HEADINGS = {
    "PAYMENT_TERMS": "1. Payment and Billing Terms",
    "IP_RIGHTS": "2. Intellectual Property Ownership",
    "LIABILITY_CAP": "3. Limitation of Liability",
    "INDEMNIFICATION": "4. Indemnification Obligations",
    "TERMINATION": "5. Term and Termination",
    "DATA_PRIVACY_SECURITY": "6. Data Privacy and Security",
    "GOVERNING_LAW": "7. Governing Law and Dispute Jurisdiction",
}

GOOD = {
    "PAYMENT_TERMS": "All undisputed invoices are payable within Net 60 days of receipt of an accurate invoice. Late payments accrue interest at the lesser of 1.0% per annum or the maximum rate permitted by law.",
    "IP_RIGHTS": "Customer retains all rights, title, and interest in Customer Data and all deliverables. All custom deliverables are work made for hire owned by Customer.",
    "LIABILITY_CAP": "Except for confidentiality breaches, each party's aggregate fees paid under this Agreement shall not exceed the preceding twelve (12) months of fees, and neither party is liable for consequential damages.",
    "INDEMNIFICATION": "Vendor shall defend, indemnify and hold harmless Customer against third-party intellectual property infringement and data breach losses.",
    "TERMINATION": "Customer may terminate this Agreement for convenience upon thirty (30) days' prior written notice without penalty.",
    "DATA_PRIVACY_SECURITY": "Vendor maintains SOC 2 Type II controls, will encrypt Customer Data, and will notify Customer within forty-eight (48) hours of a confirmed breach.",
    "GOVERNING_LAW": "This Agreement shall be construed under Delaware law. Disputes shall be resolved by binding arbitration administered by the AAA in Wilmington, Delaware.",
}

BAD = {
    "PAYMENT_TERMS": "All invoices are due upon receipt and payable within Net 15 days. Late payments incur a 1.5% per month interest surcharge.",
    "IP_RIGHTS": "Vendor retains all right, title, and interest in the platform. Customer hereby assigns to Vendor all rights in derivative works and custom deliverables.",
    "LIABILITY_CAP": "Vendor's aggregate liability shall be uncapped and without limitation, including for indirect and consequential damages.",
    "INDEMNIFICATION": "Customer shall indemnify, defend, and hold harmless Vendor. Vendor shall have no obligation to defend Customer for intellectual property infringement claims.",
    "TERMINATION": "The initial term is strictly non-cancelable. Customer has no termination for convenience and must pay an early termination fee equal to 100% of remaining fees.",
    "DATA_PRIVACY_SECURITY": "Vendor will use reasonable efforts only to protect data and will notify Customer within thirty days of confirmation of a security incident.",
    "GOVERNING_LAW": "This Agreement is governed by the laws of England and Wales, and the parties submit to the exclusive jurisdiction of the courts of London, England.",
}

EXPECTED_RULES = {
    "PAYMENT_TERMS": "RULE_PAY_005",
    "IP_RIGHTS": "RULE_IP_003",
    "LIABILITY_CAP": "RULE_LIAB_001",
    "INDEMNIFICATION": "RULE_INDEM_002",
    "TERMINATION": "RULE_TERM_006",
    "DATA_PRIVACY_SECURITY": "RULE_PRIV_007",
    "GOVERNING_LAW": "RULE_LAW_004",
}

BAD_BITS = [
    "PAYMENT_TERMS",
    "IP_RIGHTS",
    "LIABILITY_CAP",
    "INDEMNIFICATION",
    "TERMINATION",
    "DATA_PRIVACY_SECURITY",
    "GOVERNING_LAW",
]


def generate_contract(path: Path, mask: int) -> Tuple[Set[str], Set[str]]:
    import docx

    document = docx.Document()
    document.add_heading("Master Software as a Service Agreement", 0)
    document.add_paragraph(
        "This Master Software as a Service Agreement is entered into by and between the Vendor and Customer."
    )
    expected_rules: Set[str] = set()
    for index, clause_type in enumerate(BAD_BITS):
        bad = bool(mask & (1 << index))
        document.add_heading(CLAUSE_HEADINGS[clause_type], level=1)
        document.add_paragraph(BAD[clause_type] if bad else GOOD[clause_type])
        if bad:
            expected_rules.add(EXPECTED_RULES[clause_type])
    document.save(str(path))
    expected_types = set(CLAUSE_HEADINGS) | {"MISCELLANEOUS"}
    return expected_rules, expected_types


def percentile(values: List[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def evaluate(contracts: int, with_llm: bool) -> Dict:
    if not with_llm:
        os.environ["OPENCODE_API_KEY"] = ""
    os.environ.setdefault("LIVE_OSINT_ENABLED", "false")
    os.environ.setdefault("MCP_ENABLED", "false")

    from agents.orchestrator import MainOrchestrator
    from core.deal_store import DealRepository

    true_positives = 0
    false_positives = 0
    false_negatives = 0
    critical_expected = 0
    critical_found = 0
    type_matches = 0
    latencies: List[float] = []
    statuses: Dict[str, int] = {}
    total_tokens = 0
    total_cost = 0.0
    rows = []

    with tempfile.TemporaryDirectory(prefix="redliner-eval-") as directory:
        root = Path(directory)
        output_dir = root / "outputs"
        output_dir.mkdir()
        orchestrator = MainOrchestrator(
            repository=DealRepository(root / "deals.db")
        )
        for index in range(contracts):
            path = root / f"contract_{index:02d}.docx"
            expected_rules, expected_types = generate_contract(path, index)
            started = time.perf_counter()
            state = orchestrator.process_incoming_deal(
                deal_id=f"EVAL-{index:03d}",
                contract_path=path,
                vendor_name="ApexCloud Enterprise Ltd",
                output_dir=output_dir,
                max_iterations=3,
            )
            elapsed = (time.perf_counter() - started) * 1000
            latencies.append(elapsed)

            actual_rules = {action.rule_id for action in state.redline_actions}
            actual_types = {clause.clause_type.value for clause in state.parsed_clauses}
            tp = len(expected_rules & actual_rules)
            fp = len(actual_rules - expected_rules)
            fn = len(expected_rules - actual_rules)
            true_positives += tp
            false_positives += fp
            false_negatives += fn

            critical_expected += len(expected_rules & {"RULE_LIAB_001", "RULE_IP_003"})
            critical_found += len(
                expected_rules
                & actual_rules
                & {"RULE_LIAB_001", "RULE_IP_003"}
            )
            type_matches += int(expected_types == actual_types)
            statuses[state.run_status] = statuses.get(state.run_status, 0) + 1
            usage = state.llm_usage or {}
            total_tokens += int(usage.get("total_tokens") or 0)
            if isinstance(usage.get("cost_usd"), (int, float)):
                total_cost += float(usage["cost_usd"])

            rows.append(
                {
                    "contract": path.name,
                    "expected_rules": sorted(expected_rules),
                    "actual_rules": sorted(actual_rules),
                    "expected_types": sorted(expected_types),
                    "actual_types": sorted(actual_types),
                    "status": state.run_status,
                    "latency_ms": round(elapsed, 2),
                }
            )

    precision = true_positives / max(1, true_positives + false_positives)
    recall = true_positives / max(1, true_positives + false_negatives)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    critical_miss_rate = 1 - critical_found / max(1, critical_expected)
    cold_start = latencies[0] if latencies else 0.0
    warm_latencies = latencies[1:] if len(latencies) > 1 else latencies
    mean_latency = statistics.mean(warm_latencies) if warm_latencies else 0.0
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contracts": contracts,
        "llm_enabled": with_llm,
        "clause_type_accuracy": type_matches / max(1, contracts),
        "redline_precision": precision,
        "redline_recall": recall,
        "redline_f1": f1,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "critical_miss_rate": critical_miss_rate,
        "latency_ms": {
            "cold_start": round(cold_start, 2),
            "mean": round(mean_latency, 2),
            "p50": round(percentile(warm_latencies, 0.50), 2),
            "p95": round(percentile(warm_latencies, 0.95), 2),
        },
        "status_counts": statuses,
        "llm_tokens": total_tokens,
        "llm_cost_usd": round(total_cost, 6),
        "rows": rows,
    }
    return result


def to_markdown(result: Dict) -> str:
    rows = "\n".join(
        "| {contract} | {expected} | {actual} | {status} | {latency_ms} |".format(
            contract=row["contract"],
            expected=", ".join(row["expected_rules"]) or "—",
            actual=", ".join(row["actual_rules"]) or "—",
            status=row["status"],
            latency_ms=row["latency_ms"],
        )
        for row in result["rows"]
    )
    return f"""# RedLiner evaluation

Generated: `{result['generated_at']}`

## Method

- `{result['contracts']}` generated DOCX contracts with known clause types and known
  playbook violations.
- Coverage includes payment terms, IP ownership, liability caps, indemnification,
  termination, data privacy and governing law.
- Default run disables LLM, live OSINT and MCP network calls for reproducibility.
- `--with-llm` runs the CrewAI stage and records provider usage/cost.
- Latency is the full `process_incoming_deal` call, including parsing, redlining,
  vendor assessment and email drafting.

## Results

| Metric | Value |
|---|---:|
| Clause-type exact accuracy | {result['clause_type_accuracy']:.1%} |
| Redline precision | {result['redline_precision']:.1%} |
| Redline recall | {result['redline_recall']:.1%} |
| Redline F1 | {result['redline_f1']:.3f} |
| Critical miss rate | {result['critical_miss_rate']:.1%} |
| Cold-start latency | {result['latency_ms']['cold_start']:.1f} ms |
| Mean warm latency | {result['latency_ms']['mean']:.1f} ms |
| p50 warm latency | {result['latency_ms']['p50']:.1f} ms |
| p95 warm latency | {result['latency_ms']['p95']:.1f} ms |
| LLM enabled | {result['llm_enabled']} |
| Total LLM tokens | {result['llm_tokens']} |
| Reported LLM cost | ${result['llm_cost_usd']:.6f} |

## Per-contract results

| Contract | Expected rules | Detected rules | Status | Latency (ms) |
|---|---|---|---|---:|
{rows}

## Cost model

- Deterministic evaluation: **$0 model cost** by design (LLM, MCP and live OSINT disabled).
- Live CrewAI mode: OpenCode Go `glm-5.3-flash` list pricing is approximately
  $0.15/M input tokens and $0.50/M output tokens. A reference live run recorded
  about 8.9K total tokens (6.6K input, 2.3K output), or roughly **$0.002 per deal**.
- A 100-contract live run is therefore roughly **$0.20 in model usage**, excluding
  hosting. Render paid hosting is about $7/month; Supabase and Langfuse have free
  tiers for this demo.
- These are estimates, not a billing guarantee. Use `--with-llm` to record actual
  provider usage/cost for the run.

## Reproduce

```bash
cd RedLiner
PYTHONPATH=. uv run python scripts/evaluate.py --contracts 24
# Optional live CrewAI usage/cost:
PYTHONPATH=. uv run python scripts/evaluate.py --contracts 3 --with-llm
```

## Limitations

- Synthetic contract text is not a substitute for a real legal corpus.
- The evaluator targets this playbook and these clause templates.
- Deterministic mode reports zero LLM cost by design.
- No human acceptance study is included.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=int, default=24)
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--json", type=Path, default=DOCS_DIR / "evaluation_results.json")
    parser.add_argument("--markdown", type=Path, default=DOCS_DIR / "EVALUATION.md")
    args = parser.parse_args()

    result = evaluate(max(1, min(args.contracts, 50)), args.with_llm)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.markdown.write_text(to_markdown(result), encoding="utf-8")
    print(to_markdown(result))


if __name__ == "__main__":
    main()
