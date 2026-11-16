# Configuration guide — enabling every service

This page explains how the **Demo settings** panel is produced and how to turn
each service on. Most toggles are environment variables, not dashboard switches.
The dashboard panel is read-only; only **Email Delivery Settings** writes a file.

## How configuration works

RedLiner reads configuration from two places:

| Source | Used for | Notes |
|---|---|---|
| `.env` at the repository root | model, database, MCP, OSINT, guardrails, Langfuse, A2A, Gmail poller, demo auth | Loaded by `core/env.py` with `override=False`, so an already-exported shell variable wins. |
| `data/email_config.json` | SMTP / Resend provider, host, port, username, password, sender | Created once from `.env` and then becomes the source of truth. The Gmail poller also reads credentials from this file. |

Two consequences:

1. **Editing `.env` requires a server restart.** There is no hot reload for environment variables.
2. **Changing `SMTP_*` in `.env` may have no effect** if `data/email_config.json` already exists. Delete that file to re-seed it, or use the dashboard’s Email Delivery Settings form.

The **Demo settings** panel calls `GET /api/settings` and only reports what the
process currently sees:

```text
Model / Email / Database / MCP / Live OSINT / Guardrails
Langfuse / A2A / Gmail poller / Demo auth
```

## Quick start: everything on

Back up your current file first:

```bash
cd /Users/siddharthjain/Desktop/Sem7/agai/proj/RedLiner
cp .env .env.backup
```

Use this as a template. Replace the placeholder values; never commit the real file.

```dotenv
# --- Model: OpenCode Go ---
OPENCODE_API_KEY=your-opencode-key
OPENCODE_MODEL=glm-5.3-flash
# Optional: only change these for a self-hosted/proxied endpoint.
# OPENCODE_BASE_URL=https://opencode.ai/inference/go/openai/v1
# OPENCODE_ENDPOINT=https://opencode.ai/inference/go/openai/v1/chat/completions

# --- Email: Direct SMTP (Gmail example) ---
EMAIL_PROVIDER=smtp
SMTP_USER=your.address@gmail.com
SMTP_PASSWORD=your-16-character-google-app-password
SMTP_FROM=your.address@gmail.com

# --- Database: SQLite is the default ---
# Leave DATABASE_URL unset for SQLite.
# REDLINER_DB_PATH=data/redliner_deals.db
# DATABASE_URL=postgresql://user:password@host:5432/postgres

# --- MCP stdio tools ---
MCP_ENABLED=true

# --- Live OSINT ---
LIVE_OSINT_ENABLED=true
OSINT_TIMEOUT_SECONDS=5
OSINT_CACHE_TTL_SECONDS=86400
# Optional richer search; GLEIF and DuckDuckGo need no key.
TAVILY_API_KEY=
SERPER_API_KEY=

# --- Deterministic LLM guardrails ---
LLM_GUARDRAILS_ENABLED=true

# --- Langfuse Cloud tracing ---
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_ENVIRONMENT=demo
LANGFUSE_RELEASE=redliner-demo

# --- A2A vendor agent ---
A2A_ENABLED=true
A2A_VENDOR_URL=http://127.0.0.1:8001
A2A_TIMEOUT_SECONDS=30
A2A_SERVICE_TOKEN=replace-with-a-long-random-token

# --- Gmail inbox polling ---
GMAIL_POLL_ENABLED=true
GMAIL_POLL_FOLDER=RedLiner
GMAIL_POLL_INTERVAL=60
GMAIL_POLL_LIMIT=10

# --- Shared demo login ---
DEMO_USER=demo
DEMO_PASSWORD=replace-with-a-demo-password

# --- Optional ---
REVIEWER_EMAIL=
REVIEWER_WEBHOOK_URL=
APPROVAL_SECRET=replace-with-a-long-random-secret
DASHBOARD_URL=http://127.0.0.1:8000
RETENTION_DAYS=90
```

Then restart:

```bash
# Stop the running server first, then:
PYTHONPATH=. uv run python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

If you changed email values, either delete the generated file or update the
dashboard form after restart:

```bash
rm -f data/email_config.json      # re-seed from .env on next start
```

Check the effective state:

```bash
curl -u demo:YOUR_DEMO_PASSWORD http://127.0.0.1:8000/api/settings | python3 -m json.tool
```

Or run the readiness checker:

```bash
PYTHONPATH=. uv run python scripts/check_config.py
```

---

## 1. Model — OpenCode Go

**What it enables:** the CrewAI crew (procurement, finance, email drafting) and
the ADK model calls. Without a key the app still runs, but uses deterministic
fallbacks and no LLM draft.

**Required**

```dotenv
OPENCODE_API_KEY=...
OPENCODE_MODEL=glm-5.3-flash
```

**Optional**

```dotenv
OPENCODE_BASE_URL=https://opencode.ai/inference/go/openai/v1
OPENCODE_ENDPOINT=https://opencode.ai/inference/go/openai/v1/chat/completions
```

`OPENCODE_BASE_URL` is used by the CrewAI/ADK adapter (`runtime/llm.py`).
`OPENCODE_ENDPOINT` is used by the standalone email drafter (`services/opencode_llm.py`).

The workbench and email-tab preview boxes stream automatically via
`POST /api/email/draft-stream` with `stream: true`. The loading overlay disappears
at the first token and the text streams directly into the main box. This requires
a valid `OPENCODE_API_KEY`; without it, the deterministic template preview still
works. The **Regenerate Text** button re-streams when a deal ID is present.

**Steps**

1. Create an OpenCode Go key in the OpenCode Console.
2. Put it in `.env` as `OPENCODE_API_KEY`.
3. Keep or change `OPENCODE_MODEL`.
4. Restart the backend.

**Verify**

```bash
curl -u demo:PASS http://127.0.0.1:8000/api/settings
```

`model` should show the model name. Run one deal and confirm the email draft is
LLM-generated rather than the deterministic template.

**Troubleshooting**

- `status="disabled"` in the CrewAI result means the key is empty.
- A model name must be supported by OpenCode Go; `glm-5.3-flash` is the demo default.
- If you exported `OPENCODE_API_KEY` in your shell, that value wins over `.env`.

---

## 2. Email — Direct SMTP

**What it enables:** real outbound counter-proposal emails with the redlined DOCX
attached. Without it, `sandbox` mode only simulates delivery.

**Required**

```dotenv
EMAIL_PROVIDER=smtp
SMTP_USER=your.address@gmail.com
SMTP_PASSWORD=your-google-app-password
SMTP_FROM=your.address@gmail.com
```

**Gmail setup**

1. Enable **2-Step Verification** on the Google account.
2. Open <https://myaccount.google.com/apppasswords>.
3. Create an app password for “Mail”.
4. Use the 16-character password as `SMTP_PASSWORD` (spaces are optional).
5. Do **not** use the normal Google account password.

The defaults are `smtp.gmail.com:587` with STARTTLS. To use another provider,
edit `data/email_config.json` or the dashboard form and set `smtp_host`,
`smtp_port`, `smtp_use_tls`, `from_email` and `from_name`.

**Steps**

1. Set the four values above in `.env`.
2. Delete `data/email_config.json` if it already exists, or open the dashboard’s
   **Email Delivery Settings** and select **Direct SMTP**.
3. Restart.
4. In the dashboard, use **Send Test** to send a verification email.

**Verify**

```bash
curl -u demo:PASS -X POST http://127.0.0.1:8000/api/email/send-test \
  -H 'Content-Type: application/json' \
  -d '{"target_email":"you@example.com"}'
```

Or from the dashboard: **Email Delivery Settings → Send Test**.

**Troubleshooting**

- `SMTP credentials missing`: `data/email_config.json` has an empty user/password.
- `Username and Password not accepted`: use an App Password, not the account password.
- The dashboard **Demo settings** panel shows `email smtp` only after the provider
  in `data/email_config.json` is `smtp`; the `.env` value alone is not enough once
  the file exists.

---

## 3. Database — SQLite or PostgreSQL

**SQLite is the default.** No service is required.

```dotenv
# Optional override; this is the default path.
REDLINER_DB_PATH=data/redliner_deals.db
```

**PostgreSQL / Supabase** takes precedence when `DATABASE_URL` is set:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/postgres
```

The app normalizes `postgres://` and `postgresql+psycopg://` forms.

**Steps**

1. Leave `DATABASE_URL` unset for SQLite, or set it for Postgres.
2. Restart.
3. Check `GET /api/settings`; `database` should be `sqlite` or `postgres`.

**Verify**

```bash
curl -u demo:PASS http://127.0.0.1:8000/api/settings

# Also probes the actual Postgres connection.
PYTHONPATH=. uv run python scripts/check_config.py --network
```

For SQLite, the file appears at `data/redliner_deals.db` (or `REDLINER_DB_PATH`).
For Supabase, use the pooled connection string if the direct connection is
restricted. The `--network` check reports `ready (connected)` or `unreachable`
with the connection error.

**Troubleshooting**

- If `DATABASE_URL` is set but unreachable, the app fails at repository creation.
- SQLite is single-writer; use one backend process for the demo.
- `data/redliner_deals.db-wal` and `-shm` are normal.

---

## 4. MCP — stdio tools

**What it enables:** real MCP stdio servers for contract parsing, vendor lookup
and finance calculations. There are three local servers:

```text
mcp_servers/contract_tools.py
mcp_servers/vendor_tools.py
mcp_servers/finance_tools.py
```

Consumers:

- ADK: `DocumentParserNode → parse_contract`, `VendorIntelligenceNode → lookup_vendor`, `TradeoffNode → propose_tradeoff`
- CrewAI: `VendorLookupTool`, `ContractMetadataTool`, `UtilityScoreTool`, `GuardrailCheckTool`, `TradeoffProposalTool`

See the [MCP tool architecture diagram](diagrams/mcp-architecture.svg) for the
consumer → client → server flow.

**Required**

```dotenv
MCP_ENABLED=true
```

No external account or network service is needed. The client spawns
`sys.executable` with `PYTHONPATH` set to the repository root, so run the app from
the repository’s virtual environment.

**Steps**

1. Set `MCP_ENABLED=true`.
2. Restart.
3. Run a deal.

**Verify**

- `GET /api/settings` shows `mcp_enabled: true`.
- `data/mcp_audit.jsonl` gains one record per MCP call with status and duration.
- Tests: `PYTHONPATH=. uv run pytest tests/test_mcp_and_hitl.py -q`.

**Troubleshooting**

- If the server cannot start, the audit log records an error; the app degrades.
- `MCP_ENABLED=false` disables both ADK and CrewAI MCP tools.
- Do not run MCP servers manually; the client manages their lifecycle.

---

## 5. Live OSINT

**What it enables:** live corporate-registry and web checks instead of the static
vendor profile.

- **GLEIF** corporate registry: no key.
- **DuckDuckGo HTML** search: no key fallback.
- **Tavily** or **Serper**: optional richer search.

**Required**

```dotenv
LIVE_OSINT_ENABLED=true
```

**Optional**

```dotenv
OSINT_TIMEOUT_SECONDS=5
OSINT_CACHE_TTL_SECONDS=86400
TAVILY_API_KEY=
SERPER_API_KEY=
```

**Steps**

1. Set `LIVE_OSINT_ENABLED=true`.
2. Optionally add a Tavily or Serper key for better search coverage.
3. Restart.

**Verify**

Dashboard **Quick OSINT Check**, or:

```bash
curl -u demo:PASS 'http://127.0.0.1:8000/api/vendor/assess?name=Microsoft%20Corporation'
```

The response should include a risk score, tier and flags. Live OSINT failures
degrade to the static profile rather than breaking the deal.

**Troubleshooting**

- No outbound network in your environment: set `LIVE_OSINT_ENABLED=false`.
- Slow checks: lower `OSINT_TIMEOUT_SECONDS` or raise the cache TTL.
- GLEIF matches are fuzzy; use the legal company name for best results.

---

## 6. Guardrails

**What it enables:** deterministic input/output checks for prompt injection,
secret leakage, abuse and PII warnings around model calls. No external service.

**Required**

```dotenv
LLM_GUARDRAILS_ENABLED=true
```

**Steps**

1. Set the flag.
2. Restart.

**Verify**

```bash
PYTHONPATH=. uv run pytest tests/test_guardrails.py -q
```

A blocked model call appears in the deal state as `guardrail_flags` and in the
report. The CrewAI result status becomes `guardrail_blocked`.

**Troubleshooting**

- Guardrails are heuristic, not a security boundary.
- Setting the flag to `false` disables both input and output checks.

---

## 7. Langfuse — tracing

**What it enables:** cloud traces for deal, ADK, CrewAI, LLM, MCP, A2A and
approval spans. Without keys the tracing module is a no-op.

**Required**

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_TRACING_ENABLED=true
```

**Optional**

```dotenv
LANGFUSE_ENVIRONMENT=demo
LANGFUSE_RELEASE=redliner-demo
```

**Steps**

1. Create a Langfuse Cloud account and project.
2. Copy the public and secret keys.
3. Set the values above.
4. Restart.
5. Run a deal.

**Verify**

- `GET /api/settings` shows `langfuse_enabled: true` only when both keys are present and the flag is on.
- The deal object and report contain `langfuse_trace_url`.
- Open the Langfuse project and confirm the trace and its child spans.

**Troubleshooting**

- `langfuse_enabled: false` with keys present means `LANGFUSE_TRACING_ENABLED` is off or a key is blank.
- A tracing failure never blocks a deal; errors are swallowed by design.
- For a self-hosted Langfuse, change `LANGFUSE_HOST`.

---

## 8. A2A — ADK vendor agent

**What it enables:** the CrewAI procurement crew calls a separate ADK Vendor
Intelligence agent over the A2A protocol. This is a real second HTTP service.

**Backend settings**

```dotenv
A2A_ENABLED=true
A2A_VENDOR_URL=http://127.0.0.1:8001
A2A_TIMEOUT_SECONDS=30
A2A_SERVICE_TOKEN=replace-with-a-long-random-token
```

**A2A server settings** (same token)

```dotenv
A2A_HOST=127.0.0.1
A2A_PORT=8001
A2A_PROTOCOL=http
A2A_SERVICE_TOKEN=replace-with-a-long-random-token
```

**Steps**

1. Start the A2A server in a second terminal:

   ```bash
   A2A_SERVICE_TOKEN=replace-with-a-long-random-token \
   PYTHONPATH=. uv run python -m uvicorn a2a_servers.vendor_agent:app \
     --host 127.0.0.1 --port 8001
   ```

2. Set the backend’s `A2A_*` values to match.
3. Restart the backend.
4. Keep `OPENCODE_API_KEY` configured: the A2A tool is part of the CrewAI crew,
   and the crew is disabled without a model key.

**Verify**

```bash
curl -H "Authorization: Bearer $A2A_SERVICE_TOKEN" \
  http://127.0.0.1:8001/.well-known/agent-card.json
```

Then run a deal and confirm `a2a.vendor_intelligence` appears in the traces and
the deal metadata.

**Check from the frontend**

Open the dashboard → **Email** tab → **A2A vendor agent** → **Check A2A connection**.
The card calls:

```text
GET /api/a2a/status
```

It shows **Reachable** with the agent name, **Unreachable** with the error, or
**Disabled** when `A2A_ENABLED=false`. This probes the actual agent card, so it is
stronger than reading the environment flag from `/api/settings`.

**Hosted**

- AWS Compose: `deploy/aws/docker-compose.yml` starts both containers and sets
  `A2A_VENDOR_URL` from `PUBLIC_HOST`.
- Render: deploy a second web service for `a2a_servers.vendor_agent:app` (see
  `deploy/render/README.md`).

**Troubleshooting**

- `401 Unauthorized`: the token differs between backend and A2A server.
- `A2A agent returned no result`: check the A2A server logs and the agent card URL.
- Cold starts can exceed a short timeout; raise `A2A_TIMEOUT_SECONDS`.
- `A2A_ENABLED` is read when the CrewAI runtime is constructed; restart after changing it.

---

## 9. Gmail poller — inbound contracts

**What it enables:** the hosted backend polls a Gmail label over IMAP, downloads
`.docx`/`.pdf` attachments, and starts a deal. It drafts replies but does not send
them automatically.

**Required**

```dotenv
GMAIL_POLL_ENABLED=true
GMAIL_POLL_FOLDER=RedLiner
GMAIL_POLL_INTERVAL=60
GMAIL_POLL_LIMIT=10
```

**Gmail setup**

1. Enable **IMAP** in Gmail: Settings → Forwarding and POP/IMAP → Enable IMAP.
2. Create a label named exactly `RedLiner`.
3. Create a filter that applies the label to vendor contract emails, for example
   `subject:(contract OR agreement OR proposal)` → apply label `RedLiner`.
4. Use the same Gmail address and App Password as SMTP.

The poller reads credentials from `data/email_config.json`, so make sure that file
has the Gmail user and App Password.

**Steps**

1. Set the four `GMAIL_*` values.
2. Confirm SMTP credentials are present and the provider is `smtp`.
3. Restart. The poller starts inside the FastAPI lifespan.
4. Send a test email with a `.docx` attachment to the labelled address.

**Verify**

- Server log: `[inbox-worker] polling Gmail label 'RedLiner' every 60s`.
- `data/incoming/gmail_poller_runs.jsonl` records each poll.
- The deal appears in `/deals.html`.

### Sending a sample contract to the poller

Five test fixtures are included:

```text
data/sample_contracts/sample_clean_saas_agreement.docx
data/sample_contracts/sample_medium_risk_saas_agreement.docx
data/sample_contracts/sample_professional_services_agreement.docx
data/sample_contracts/sample_data_processing_addendum.docx
data/sample_contracts/sample_unfavorable_saas_agreement.docx
```

| Sample | Expected result |
|---|---|
| `sample_clean_saas_agreement.docx` | Converged, 0 redlines |
| `sample_medium_risk_saas_agreement.docx` | 3 findings: payment, termination, privacy |
| `sample_professional_services_agreement.docx` | 2 findings: payment, governing law |
| `sample_data_processing_addendum.docx` | 6 findings, at least one critical |
| `sample_unfavorable_saas_agreement.docx` | 7 findings, human review |

Send one to the address configured in `data/email_config.json` from the dashboard’s
**Send sample contracts** card, or from the CLI:

```bash
PYTHONPATH=. uv run python scripts/send_sample_contract.py --list
PYTHONPATH=. uv run python scripts/send_sample_contract.py \
  --contract sample_unfavorable_saas_agreement.docx --dry-run
PYTHONPATH=. uv run python scripts/send_sample_contract.py \
  --contract sample_unfavorable_saas_agreement.docx
```

The dashboard card calls `GET /api/email/samples` and
`POST /api/email/send-sample`. It sends to the address in
`data/email_config.json` unless you enter a different recipient.

The recipient defaults to `SMTP_USER`; use `--to you@example.com` to override it.
The script reads SMTP credentials from the existing email configuration and never
prints the password.

The message subject starts with `[RedLiner]`. Create a Gmail filter that applies
the `RedLiner` label to that subject, or apply the label manually. Then either
start the backend with the poller enabled, or process the label once:

```bash
PYTHONPATH=. uv run python scripts/gmail_inbox_poller.py --once --folder RedLiner
```

To test the inbound webhook without Gmail, use the same script with a running
backend:

```bash
PYTHONPATH=. uv run python scripts/send_sample_contract.py \
  --contract sample_unfavorable_saas_agreement.docx --local-webhook
```

**Troubleshooting**

- Run exactly **one** backend instance; two pollers can process the same message.
- `Gmail credentials missing`: fix `data/email_config.json`.
- Messages must match the label/filter, not just the inbox.
- Render free services sleep; the poller pauses while asleep. Use AWS Lightsail
  or a keep-warm ping for reliable polling.

---

## 10. Demo auth — shared Basic Auth

**What it enables:** one shared username/password in front of the dashboard and
APIs. It is intentionally not a user system.

**Required**

```dotenv
DEMO_USER=demo
DEMO_PASSWORD=replace-with-a-demo-password
```

Leave `DEMO_PASSWORD` empty to disable auth for local work.

**Steps**

1. Set both values.
2. Restart.
3. Open the dashboard; the browser prompts for the credentials.

**Verify**

```bash
curl -i http://127.0.0.1:8000/api/deals
# 401 without credentials
curl -u demo:PASS http://127.0.0.1:8000/api/deals
# 200 with credentials
```

`/api/health` and `/api/webhook/*` are intentionally exempt.

**Troubleshooting**

- The password is sent over HTTP; use TLS in front of a public deployment.
- This is not Supabase Auth, RLS or per-user authorization.
- Changing the password requires a restart.

---

## 11. Optional services

### Reviewer notifications

```dotenv
REVIEWER_EMAIL=you@example.com
REVIEWER_WEBHOOK_URL=
APPROVAL_SECRET=replace-with-a-long-random-secret
DASHBOARD_URL=http://127.0.0.1:8000
```

Used for human-review notifications and approval links. `APPROVAL_SECRET` should
be long and random.

### Retention purge

```dotenv
RETENTION_DAYS=90
```

Run the purge manually or from a scheduled job:

```bash
PYTHONPATH=. uv run python scripts/purge_retention.py --days 90 --artifacts
```

### Inbound webhook / Cloudflare email

```dotenv
REDLINER_WEBHOOK_TOKEN=replace-with-a-token
CLOUDFLARE_WORKER_URL=http://127.0.0.1:8787
CLOUDFLARE_DISPATCH_TOKEN=
```

`REDLINER_WEBHOOK_TOKEN` protects `/api/webhook/email`. The Cloudflare Worker is
an alternative inbound path; the Gmail poller does not need it.

---

## Verification checklist

```bash
# 1. Effective settings
curl -u demo:PASS http://127.0.0.1:8000/api/settings | python3 -m json.tool

# 2. Readiness of every service
PYTHONPATH=. uv run python scripts/check_config.py

# 3. Full test suite
PYTHONPATH=. uv run pytest -q

# 4. Email
curl -u demo:PASS -X POST http://127.0.0.1:8000/api/email/send-test \
  -H 'Content-Type: application/json' -d '{"target_email":"you@example.com"}'

# 5. OSINT
curl -u demo:PASS 'http://127.0.0.1:8000/api/vendor/assess?name=Microsoft%20Corporation'

# 6. A2A
curl -H "Authorization: Bearer $A2A_SERVICE_TOKEN" \
  http://127.0.0.1:8001/.well-known/agent-card.json

# 7. MCP activity
tail -n 5 data/mcp_audit.jsonl

# 8. Gmail poller activity
tail -n 5 data/incoming/gmail_poller_runs.jsonl
```

## Hosted deployments

- AWS Lightsail all-in-one: `deploy/aws/README.md`
- Render free: `deploy/render/README.md`
- Cost comparison: `deploy/README.md`

The same environment variables apply. On AWS Compose, `PUBLIC_HOST` drives the
A2A URL. On Render, deploy the A2A service separately or set
`A2A_ENABLED=false`.

## Common configuration mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Demo settings stay `off` after editing `.env` | Server not restarted | Restart the backend |
| Email still `sandbox` after setting `EMAIL_PROVIDER=smtp` | `data/email_config.json` already exists and overrides `.env` | Delete the file or save via the dashboard |
| Gmail poller says credentials missing | Email config has no user/password | Fill SMTP user + App Password |
| Langfuse shows off with keys set | One key blank or tracing flag off | Set both keys and `LANGFUSE_TRACING_ENABLED=true` |
| A2A tool never appears | CrewAI disabled or backend not restarted | Set `OPENCODE_API_KEY` and restart |
| Basic Auth does not prompt | `DEMO_PASSWORD` empty | Set a password and restart |
| `DATABASE_URL` ignored | It is set in a different shell or `.env` not loaded | Check the process environment |
