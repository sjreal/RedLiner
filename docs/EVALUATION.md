# RedLiner evaluation

Generated: `2026-11-14T16:13:20Z`

## Method

- `24` generated DOCX contracts with known clause types and known
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
| Clause-type exact accuracy | 100.0% |
| Redline precision | 100.0% |
| Redline recall | 100.0% |
| Redline F1 | 1.000 |
| Critical miss rate | 0.0% |
| Cold-start latency | 229.1 ms |
| Mean warm latency | 60.1 ms |
| p50 warm latency | 59.2 ms |
| p95 warm latency | 69.8 ms |
| LLM enabled | False |
| Total LLM tokens | 0 |
| Reported LLM cost | $0.000000 |

## Per-contract results

| Contract | Expected rules | Detected rules | Status | Latency (ms) |
|---|---|---|---|---:|
| contract_00.docx | — | — | CONVERGED | 229.13 |
| contract_01.docx | RULE_PAY_005 | RULE_PAY_005 | DRAFT_READY | 59.84 |
| contract_02.docx | RULE_IP_003 | RULE_IP_003 | AWAITING_HUMAN_REVIEW | 60.08 |
| contract_03.docx | RULE_IP_003, RULE_PAY_005 | RULE_IP_003, RULE_PAY_005 | AWAITING_HUMAN_REVIEW | 57.95 |
| contract_04.docx | RULE_LIAB_001 | RULE_LIAB_001 | AWAITING_HUMAN_REVIEW | 57.25 |
| contract_05.docx | RULE_LIAB_001, RULE_PAY_005 | RULE_LIAB_001, RULE_PAY_005 | AWAITING_HUMAN_REVIEW | 57.56 |
| contract_06.docx | RULE_IP_003, RULE_LIAB_001 | RULE_IP_003, RULE_LIAB_001 | AWAITING_HUMAN_REVIEW | 59.23 |
| contract_07.docx | RULE_IP_003, RULE_LIAB_001, RULE_PAY_005 | RULE_IP_003, RULE_LIAB_001, RULE_PAY_005 | AWAITING_HUMAN_REVIEW | 69.75 |
| contract_08.docx | RULE_INDEM_002 | RULE_INDEM_002 | DRAFT_READY | 59.32 |
| contract_09.docx | RULE_INDEM_002, RULE_PAY_005 | RULE_INDEM_002, RULE_PAY_005 | DRAFT_READY | 58.02 |
| contract_10.docx | RULE_INDEM_002, RULE_IP_003 | RULE_INDEM_002, RULE_IP_003 | AWAITING_HUMAN_REVIEW | 56.99 |
| contract_11.docx | RULE_INDEM_002, RULE_IP_003, RULE_PAY_005 | RULE_INDEM_002, RULE_IP_003, RULE_PAY_005 | AWAITING_HUMAN_REVIEW | 59.73 |
| contract_12.docx | RULE_INDEM_002, RULE_LIAB_001 | RULE_INDEM_002, RULE_LIAB_001 | AWAITING_HUMAN_REVIEW | 71.24 |
| contract_13.docx | RULE_INDEM_002, RULE_LIAB_001, RULE_PAY_005 | RULE_INDEM_002, RULE_LIAB_001, RULE_PAY_005 | AWAITING_HUMAN_REVIEW | 59.23 |
| contract_14.docx | RULE_INDEM_002, RULE_IP_003, RULE_LIAB_001 | RULE_INDEM_002, RULE_IP_003, RULE_LIAB_001 | AWAITING_HUMAN_REVIEW | 57.93 |
| contract_15.docx | RULE_INDEM_002, RULE_IP_003, RULE_LIAB_001, RULE_PAY_005 | RULE_INDEM_002, RULE_IP_003, RULE_LIAB_001, RULE_PAY_005 | AWAITING_HUMAN_REVIEW | 61.79 |
| contract_16.docx | RULE_TERM_006 | RULE_TERM_006 | DRAFT_READY | 60.31 |
| contract_17.docx | RULE_PAY_005, RULE_TERM_006 | RULE_PAY_005, RULE_TERM_006 | DRAFT_READY | 60.12 |
| contract_18.docx | RULE_IP_003, RULE_TERM_006 | RULE_IP_003, RULE_TERM_006 | AWAITING_HUMAN_REVIEW | 60.86 |
| contract_19.docx | RULE_IP_003, RULE_PAY_005, RULE_TERM_006 | RULE_IP_003, RULE_PAY_005, RULE_TERM_006 | AWAITING_HUMAN_REVIEW | 59.03 |
| contract_20.docx | RULE_LIAB_001, RULE_TERM_006 | RULE_LIAB_001, RULE_TERM_006 | AWAITING_HUMAN_REVIEW | 57.14 |
| contract_21.docx | RULE_LIAB_001, RULE_PAY_005, RULE_TERM_006 | RULE_LIAB_001, RULE_PAY_005, RULE_TERM_006 | AWAITING_HUMAN_REVIEW | 58.66 |
| contract_22.docx | RULE_IP_003, RULE_LIAB_001, RULE_TERM_006 | RULE_IP_003, RULE_LIAB_001, RULE_TERM_006 | AWAITING_HUMAN_REVIEW | 57.48 |
| contract_23.docx | RULE_IP_003, RULE_LIAB_001, RULE_PAY_005, RULE_TERM_006 | RULE_IP_003, RULE_LIAB_001, RULE_PAY_005, RULE_TERM_006 | AWAITING_HUMAN_REVIEW | 62.79 |

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
