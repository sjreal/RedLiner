# RedLiner — remaining implementation roadmap

This is the checklist from the current local prototype to a submittable final
project. It covers the synopsis features and all 11 minimum requirements.

## 0. Baseline already working

- DOCX/PDF parsing and typed clause objects.
- Deterministic playbook matching and native Word tracked changes/comments.
- SQLite vendor intelligence and risk scoring.
- Procurement, finance/trade-off and utility calculations (not yet fully wired
  into every deal path).
- **CrewAI + Google ADK runtime** (`runtime/crew_runtime.py`,
  `runtime/adk_runtime.py`) with ADK parallel legal/vendor branches, commercial
  checks and approval routing, plus a CrewAI procurement/finance/email crew.
- OpenCode Go LLM email/crew generation with Pydantic task outputs and template
  fallback.
- Prompt-injection checks on inbound email, webhook token, local JSONL traces,
  Gmail SMTP outbound, Cloudflare Worker inbound/outbound, Gmail IMAP poller.
- FastAPI API, dashboard, 78 tests (core, API, framework, MCP, A2A status, GLEIF matching, OSINT, guardrails, Langfuse tracing, LLM streaming, email threading, sample fixtures, sample mailer, storage, demo auth, reports, failure paths and HITL).

## 1. Blocking decision: framework compliance — resolved

The rubric says: **use CrewAI and ADK; do not use another agent framework.**
The runtime migration is done:

- [x] Created `runtime/crew_runtime.py` for CrewAI agents/tasks/crew.
- [x] Created `runtime/adk_runtime.py` for the ADK workflow.
- [x] Mapped responsibilities:
  - CrewAI: Procurement Negotiator, Finance/Compliance Reviewer, Email Writer.
  - ADK: Document Parser, Legal Review, Vendor Intelligence, Tradeoff Engine,
    Approval Gate, Review Summary.
- [ ] CrewAI hierarchical process — currently sequential; the ADK root workflow
  supplies the supervisor/parallel behavior.
- [x] Used ADK `SequentialAgent` and `ParallelAgent` for document, vendor,
  tradeoff and approval stages.
- [x] One top-level coordinator: `MainOrchestrator` shares state between ADK and
  CrewAI.
- [x] Kept deterministic Python tools behind the agents.
- [x] Removed `langgraph` from `pyproject.toml` and the runtime.
- [x] Updated `/api/health`, README, tests and the milestone docs.
- [ ] Redraw the legacy `a.py`/`b.py` diagrams with CrewAI/ADK labels.
- [x] Added framework runtime tests (`tests/test_framework_runtime.py`). The
  CrewAI path is tested with the key absent; a live CrewAI smoke run was
  performed manually and returned a successful structured crew result.

## 2. A2A interoperability

- [x] Implement an A2A server for the ADK Vendor Intelligence agent.
- [x] Publish its agent card at `/.well-known/agent-card.json`.
- [x] Implement A2A client/tool access from a CrewAI agent.
- [ ] Add authentication/OAuth or mTLS to the A2A server (currently local-only).
- [x] Add timeout/error handling and a JSON result contract.
- [x] Demonstrate the CrewAI agent receiving the ADK vendor profile.
- [x] Add an end-to-end test: CrewAI → A2A → ADK → result → CrewAI.
- [ ] Add A2A request/response to Langfuse/OTel.
- [ ] Document the protocol version and remote deployment fallback.

Acceptance: one agent defined in ADK and one in CrewAI exchange a real task over
A2A; neither is a local Python function call.

## 3. MCP tool integration

At least two real tools must be exposed through MCP, not only imported as
libraries.

- [x] Add the official MCP Python SDK and framework adapters.
- [x] Build `mcp_servers/contract_tools.py`:
  - `parse_contract` (DOCX/PDF)
  - `file_metadata`
  - validate path allowlist, size and suffix
  - [ ] separate `segment_clauses` tool (segmentation is inside `parse_contract`)
- [x] Build `mcp_servers/vendor_tools.py`:
  - `lookup_vendor`
  - `sanctions_screen`
  - `domain_age`
  - [ ] live web search/registry source
- [x] Build `mcp_servers/finance_tools.py`:
  - `utility_score`
  - `guardrail_check`
  - `propose_tradeoff`
- [x] Expose three real stdio MCP servers.
- [ ] Add authentication/timeouts/rate limits for remotely hosted MCP.
- [x] Connect MCP to ADK (contract + vendor nodes) and CrewAI (`vendor_lookup` tool).
- [x] Keep deterministic fallback when MCP is unavailable.
- [ ] Remove every duplicate direct call (fallbacks remain intentionally).
- [x] Add MCP integration tests (`tests/test_mcp_and_hitl.py`).
- [x] Log each MCP call to `data/mcp_audit.jsonl` with redacted args/duration/status.

Acceptance: a demo trace shows at least two external tools invoked over MCP.

## 4. State, persistence, HITL and convergence

### State and persistence

- [x] Define a stable `DealState` Pydantic model for both frameworks.
- [x] Add a `DealRepository` backed by SQLite and a `PostgresDealRepository`
  selectable with `DATABASE_URL` (Supabase compatible).
- [x] Tables: deals, events and immutable snapshots.
- [ ] Separate normalized tables for messages/clauses/redlines/approvals.
- [x] Persist completed, blocked and failed pipeline states with `deal_id`.
- [ ] Persist after every individual agent step.
- [ ] Add optimistic locking and idempotency keys.
- [x] Add basic retention purge for events, snapshots, outbound messages and
  generated artifacts (`RETENTION_DAYS`, `scripts/purge_retention.py`).
- [ ] Add legal-hold/retention policy per artifact type and storage backend.
- [ ] Add a migration script and seed data.

### Human approval

- [x] Replace flag-only HITL with persisted status and resumable API operations.
- [x] `GET /api/deals`, `GET /api/deals/{id}`, `/events` and `/history`.
- [x] `POST /api/deals/{id}/decision` with `APPROVE`, `REJECT`, `MANUAL_EDIT`,
  reviewer and notes.
- [x] Resume without holding an HTTP request open.
- [x] On reject/manual edit, write feedback into state and re-run the agents.
- [x] Edited-clause payload in the decision API (stored; future UI can render it).
- [x] Basic `/deals.html` approval workbench with approve/reject/manual edit,
  counteroffers, history and email preview.
- [x] Reviewer email/webhook notification with a signed review link.
- [ ] Approval-token enforcement, expiry UI and reviewer authentication.

### Convergence / re-negotiation

- [x] Ingest vendor counteroffers through a manual API.
- [x] Reply-email/webhook ingestion and `In-Reply-To`/`X-RedLiner-Deal` matching.
- [x] Extract price, Net terms and liability caps automatically (deterministic).
- [ ] Add LLM extraction fallback for complex prose.
- [x] Recompute utility/guardrails and generate the next redline.
- [x] Implement a bounded iteration loop: `max_iterations` and convergence reasons.
- [x] Add an explicit ADK `LoopAgent` for internal commercial concession rounds.
- [ ] Move the external vendor-reply loop into ADK/durable session execution.
- [x] Define convergence: no open redlines, human approval, max iterations.
- [x] Stop at max iterations and escalate to human review.
- [x] Persist immutable snapshots for every state version.
- [x] Add tests for approve, reject, counteroffer and max-iteration paths.

Acceptance: a second-round vendor counteroffer changes the plan and the loop
terminates with a recorded reason.

## 5. Complete the agent behavior

- [x] Procurement/contract: extract price, Net terms, liability basis, initial
  term and SLA signal from parsed clauses; derive a policy target when no manual
  target is supplied.
- [ ] Finance: extract annual value, currency and penalties in addition to the
  existing payment-term extraction.
- [x] Vendor: GLEIF registry (normalized/fuzzy matching, suffix handling,
  country/legal-form disambiguation, ambiguity candidates) plus optional
  Tavily/Serper/DuckDuckGo search and provenance/timestamps; failures fall back
  to the static profile.
- [ ] Legal: LLM-assisted clause classification/explanation with deterministic
  fallback; validate every replacement against the source paragraph.
- [ ] Human Approval: LLM-assisted plain-English summary with explicit facts,
  source references and confidence.
- [x] Email Writer: draft from validated deal facts, support reply threading,
  never invent terms.
- [x] Add a final `DealReport` Pydantic schema (JSON + Markdown table) containing
  clauses, redlines, risk, utility, iterations, approvals, usage and trace ID.
- [x] Add `GET /api/deals/{id}/report?format=json|markdown`.
- [x] Validate final output against the schema before returning/downloading.

## 6. Guardrails and security

### Input and file safety

- [ ] Enforce file size, extension and MIME/magic-byte checks.
- [ ] Guard against DOCX zip bombs, path traversal, macros and malformed XML.
- [ ] Sanitize/limit email HTML and attachments.
- [x] Prompt-injection, toxicity/abuse and PII warning checks.
- [x] Treat email/contract text as untrusted data in LLM/CrewAI prompts.
- [ ] Add webhook HMAC/timestamp/replay protection in addition to the token.

### Tool and output safety

- [ ] Validate every MCP/tool response with Pydantic and reject unexpected
  fields/types.
- [ ] Allowlist external tools and domains.
- [ ] Enforce budget, liability and playbook guardrails after LLM output.
- [x] Validate LLM JSON with Pydantic; fall back to the safe template on failure
  or guardrail block.
- [x] Guardrail-blocked output cannot become the outbound body.
- [ ] Add an outbound email allowlist for demo mode.

### Application security

- [ ] Add authentication/authorization to the dashboard and mutating APIs.
- [ ] Restrict CORS.
- [ ] Add rate limiting and request size limits.
- [ ] Move SMTP/OpenCode/Resend secrets to a secret manager; stop storing
  plaintext passwords in `data/email_config.json` for production.
- [ ] Protect against CSRF for browser forms if cookie auth is used.
- [ ] Add dependency and secret scanning in CI.
- [ ] Add tests for malicious prompts, oversized files, bad tool returns,
  unauthorized approvals and webhook replay.

## 7. Observability and audit

- [x] Add Langfuse Cloud SDK and environment config with no-op fallback.
- [x] Trace deal workflow, all custom ADK nodes, CrewAI crew, OpenCode generation,
  MCP tools, A2A tool, email draft, approval and counteroffer events.
- [ ] Trace every individual CrewAI task/LLM turn and every ADK model callback.
- [x] Attach `deal_id`/`trace_id`, framework, model, tokens and reported cost
  where available.
- [x] Keep trace inputs to metadata/counts; do not send full contract or email body.
- [ ] Add explicit CrewAI step/task and ADK model/tool callbacks.
- [x] Keep JSONL/local audit fallback.
- [x] Add trace URL/ID to deal state and `DealReport`.
- [ ] Add aggregate metrics: convergence rate, p50/p95, cost per deal, override rate.
- [ ] Add alerting for repeated failures and budget overruns.
- [x] Retain immutable audit events/snapshots for approvals and email identity.

## 8. UI and API completion

- [x] Deal list with status, iteration, risk, utility and token/cost summary
  (owner is intentionally omitted for the single-user demo).
- [x] Deal detail: contract clauses, redlines, vendor risk, utility, review
  summary, email and trace link.
- [x] Approval screen with approve/reject/manual-edit, notes and edited-clause JSON.
- [x] Negotiation history, counteroffer form and extraction display.
- [x] Email preview and deal-scoped dispatch.
- [x] Download redlined DOCX and JSON/Markdown report.
- [x] Playbook/SMTP settings on the main dashboard, effective model/demo settings
  on the workbench, and `/api/settings`.
- [x] Sample/test actions are explicitly labelled as demo actions.
- [x] Loading/error states and a responsive workbench layout.
- [x] OpenAPI request examples for decisions, counteroffers and dispatch.

## 9. Tests and evaluation

### Test suite

- [x] Unit tests for parser, playbook, redline, finance, vendor, guardrails.
- [x] Integration tests for MCP servers and the A2A endpoint.
- [x] E2E tests for clean/critical contracts, vendor rejection, manual edit,
  injection and invalid input.
- [ ] Failure tests for LLM timeouts, SMTP failure and webhook retry.
- [x] Security tests for demo auth, prompt injection, guardrails and service token.
- [ ] Frontend/browser E2E tests.
- [x] GitHub Actions CI runs the Python test suite.
- [ ] Measure and record coverage.

### Evaluation

- [x] Create a 24-contract generated evaluation set across risk levels.
- [x] Measure clause-type accuracy, redline precision/recall/F1 and critical miss
  rate. Human acceptance remains a separate manual study.
- [x] Measure end-to-end p50/p95/mean latency.
- [x] Record token/cost data and provide live `--with-llm` mode.
- [x] Record convergence/status counts.
- [x] Include a model-cost projection per 100 deals and monthly infrastructure
  estimate.
- [x] Publish `docs/EVALUATION.md` with tables and methodology.
- [x] Add reproducible commands and raw JSON results.

## 10. Deployment and operations

- [ ] Add a `Dockerfile` and `.dockerignore` for the backend.
- [ ] Add a production start command and health check.
- [ ] Deploy the backend to Render/Railway/Fly/VPS (Cloudflare Workers cannot
  host this Python app).
- [x] PostgreSQL/Supabase repository for deals and audit history.
- [ ] Add Supabase Storage/persistent volume for artifacts and backups.
- [ ] Run the Gmail poller in the same container/process manager as the backend,
  or use a queue worker with shared storage.
- [ ] Add a queue/retry/dead-letter path for inbound attachments and outbound
  emails.
- [ ] Deploy the Cloudflare Worker only if a domain is available; otherwise use
  the Gmail IMAP path.
- [ ] If using a domain: Email Routing, SPF/DKIM/DMARC and inbound token.
- [ ] If using SMTP: app password/secret, verified From, bounce handling.
- [ ] Add CI/CD, environment separation, logs, backups and restore drill.
- [ ] Add WAF/Cloudflare Access/rate limiting for the public demo.
- [ ] Record the deployed URL and a smoke test.
- [ ] Add a rollback procedure.

## 11. Documentation, demo and submission

- [x] Replace the README claims that the runtime is LangGraph.
- [ ] Redraw `a.py`/`b.py` diagrams with CrewAI/ADK/A2A/MCP labels; do not show
  LangGraph as the execution framework.
- [ ] Add an architecture diagram showing the A2A boundary and MCP servers.
- [ ] Add a rubric matrix: every criterion → file, demo timestamp, test evidence.
- [ ] Add setup, run, test, deploy and troubleshooting instructions.
- [ ] Add a 5–10 minute demo script:
  1. clean contract
  2. critical liability contract → HITL
  3. approve, reject and manual edit
  4. vendor counteroffer → second iteration
  5. A2A/MCP/Langfuse trace
  6. report export
- [ ] Prepare sample contracts and a seeded vendor/playbook dataset.
- [ ] Capture screenshots and a backup demo video.
- [ ] Verify `.env`, keys, logs and generated documents are not committed.
- [ ] Commit the final code and tag the submission.

## Suggested order

1. Framework decision and CrewAI/ADK migration.
2. A2A bridge.
3. MCP servers and framework wiring.
4. Persistent state + real HITL + convergence.
5. Guardrails and application security.
6. Langfuse observability.
7. UI/API completion.
8. Tests and evaluation.
9. Deployment and operations.
10. Diagrams, README, rubric matrix and demo.

## Definition of done for the 11 criteria

1. State is shared and persisted across agents and resumes.
2. At least two tools are exposed and used over MCP.
3. Final report is Pydantic-validated JSON and Markdown.
4. Supervisor, parallel, loop, HITL and A2A patterns are demonstrated.
5. CrewAI and ADK callbacks produce traces and error logs.
6. A CrewAI agent and an ADK agent exchange a real A2A task.
7. No forbidden runtime framework remains.
8. Input, tool and output guardrails block bad cases.
9. Langfuse traces show provenance and audit.
10. Evaluation reports latency, cost and quality.
11. A public deployment is reachable and documented.
