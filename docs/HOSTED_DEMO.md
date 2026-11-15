# Hosted demo — nothing running locally

For deployment options and cost comparison, see
[`../deploy/README.md`](../deploy/README.md). The cheapest all-in-one path is
[`AWS Lightsail`](../deploy/aws/README.md); the zero-cost path is
[`Render free`](../deploy/render/README.md).

YAGNI deployment for a college demo:

- one Render web service for FastAPI + dashboard + Gmail IMAP polling
- one Render web service for the ADK A2A agent
- Supabase PostgreSQL for deals and audit history
- Gmail SMTP for outbound mail
- no Supabase Auth, no RLS, no OAuth, no local `uvicorn`, no local tunnel

Security is deliberately minimal: one shared Basic Auth login for the dashboard
and APIs, a webhook token, and a service token for A2A. Do not present this as a
production security architecture.

## 1. Supabase database

1. Create a Supabase project.
2. Copy the **database connection string** (use the pooler URL if available).
3. Do not use Supabase Auth, RLS or Storage for this demo.
4. Set:

```dotenv
DATABASE_URL=postgresql://postgres.<project>:<password>@<host>:6543/postgres
```

The application creates its tables on startup. The SQLite path is only a
zero-configuration fallback for local development; the hosted demo must use
`DATABASE_URL`.

## 2. Backend on Render

Create a **Web Service** from the GitHub repository:

- Runtime: Docker
- Dockerfile: `RedLiner/Dockerfile`
- Root directory: `RedLiner`
- Health check: `/api/health`

Environment:

```dotenv
DATABASE_URL=...
OPENCODE_API_KEY=...
OPENCODE_MODEL=glm-5.3-flash
MCP_ENABLED=true
LIVE_OSINT_ENABLED=true
LLM_GUARDRAILS_ENABLED=true
TAVILY_API_KEY=
SERPER_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=demo
A2A_ENABLED=true
A2A_VENDOR_URL=https://<a2a-service>.onrender.com
A2A_SERVICE_TOKEN=<long-random-token>
A2A_TIMEOUT_SECONDS=20

EMAIL_PROVIDER=smtp
SMTP_USER=your.address@gmail.com
SMTP_PASSWORD=your-google-app-password
SMTP_FROM=your.address@gmail.com
REDLINER_WEBHOOK_TOKEN=<optional, for Cloudflare webhook only>

DEMO_USER=demo
DEMO_PASSWORD=<long-demo-password>
REVIEWER_EMAIL=your.address@gmail.com
RETENTION_DAYS=90

GMAIL_POLL_ENABLED=true
GMAIL_POLL_FOLDER=RedLiner
GMAIL_POLL_INTERVAL=60
GMAIL_POLL_LIMIT=10
```

`GMAIL_POLL_ENABLED=true` starts the Gmail poller **inside the hosted backend**.
The Gmail label `RedLiner` must exist and the Gmail account must have IMAP enabled.
On Render’s free plan the service sleeps; use a paid instance for a live demo.

## 3. A2A service on Render

Create a second Render Web Service from the same repository/Dockerfile:

- Docker Command:

```bash
PYTHONPATH=. .venv/bin/uvicorn a2a_servers.vendor_agent:app --host 0.0.0.0 --port 8001
```

- Environment:

```dotenv
A2A_HOST=<a2a-service>.onrender.com
A2A_PORT=443
A2A_PROTOCOL=https
A2A_SERVICE_TOKEN=<same token as backend>
```

The public HTTPS URL is the service hostname; Render forwards it to the container
port. The ADK agent card is served at:

```text
https://<a2a-service>.onrender.com/.well-known/agent-card.json
```

## 4. Use the demo

Open the backend URL. The browser prompts for the `DEMO_USER` /
`DEMO_PASSWORD` Basic Auth credentials.

- Main dashboard: `/`
- Deal review workbench: `/deals.html`
- Health check: `/api/health` (public)

The shared login protects the dashboard and deal APIs. The webhook and A2A service
have separate tokens.

## 5. Inbound mail without a domain

No Cloudflare or ngrok is needed:

1. Gmail Settings → Forwarding and POP/IMAP → enable IMAP.
2. Create the `RedLiner` label.
3. Create a filter that applies that label to contract mail.
4. Send a `.docx` or `.pdf` contract to the Gmail account.
5. The hosted backend polls the label, processes the contract, and stores the deal
   in Supabase.
6. Review and dispatch from `/deals.html` or the email tab.

## 6. Demo sequence

1. Send a contract to the Gmail label.
2. Wait for the hosted poller.
3. Open `/deals.html`, show the persisted deal.
4. Approve/reject/manual edit.
5. Apply a counteroffer.
6. Show a new iteration and snapshot.
7. Show the A2A vendor result.
8. Show the MCP tool audit log or `/api/health`.

## Deliberately omitted

- Supabase Auth, MFA, OAuth, RLS
- reviewer roles and per-deal assignment
- signed-token enforcement (the link is convenience only)
- durable notification outbox
- S3/Supabase Storage retention
- Langfuse/OTel

Add those only if the project outgrows the demo.
