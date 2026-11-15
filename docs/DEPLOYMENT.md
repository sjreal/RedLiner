# Deploy RedLiner with Cloudflare email

This is the production-shaped setup:

```
vendor email
    |
    v
Cloudflare Email Routing  --(inbound MIME)-->  Cloudflare Worker
                                                     |
                                                     | HTTPS POST
                                                     v
                                         FastAPI + CrewAI/ADK backend
                                         (Render / Railway / Fly / VPS)
                                                     |
                                                     | Direct SMTP
                                                     v
                                             vendor receives reply
```

Cloudflare owns the inbound email edge and the Worker. The Python backend still
needs a normal public HTTPS host; it cannot run in a Workers isolate.

For the cheapest reliable all-in-one deployment, use the AWS Lightsail Compose
stack in [`../deploy/aws/README.md`](../deploy/aws/README.md). For a zero-cost
Render demo, see [`../deploy/render/README.md`](../deploy/render/README.md).

## Prerequisites

- A domain using Cloudflare DNS.
- A Cloudflare account.
- A Render (or Railway/Fly/VPS) account or, for a temporary demo, `cloudflared`.
- A Git repository containing this project, pushed to GitHub.
- A Gmail account with 2-Step Verification enabled and an App Password, if using
  Direct SMTP through Gmail.
- A local `.env`; never commit it.

## 1. Verify Direct SMTP locally first

Create a local environment file if you do not already have one:

```bash
cd RedLiner
test -f .env || cp .env.example .env
```

Set these values in `.env`:

```dotenv
EMAIL_PROVIDER=smtp
SMTP_USER=your.address@gmail.com
SMTP_PASSWORD=your-google-app-password
SMTP_FROM=your.address@gmail.com
OPENCODE_API_KEY=your-opencode-key
OPENCODE_MODEL=glm-5.3-flash
```

Start the backend:

```bash
uv sync --python 3.12
PYTHONPATH=. uv run python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --reload
```

In the dashboard, choose **Direct SMTP**, confirm host `smtp.gmail.com`, port
`587`, your Gmail address and App Password, then save. Send a test email to
yourself and confirm the response has `is_real_delivery: true`. Do not continue
until this works.

Use a Google **App Password**, not your normal account password. Gmail SMTP
sends from the Gmail address (or a verified “Send mail as” alias), not
automatically from your Cloudflare domain.

## 2. Push the project to GitHub

`.env`, `.dev.vars`, generated documents and local logs must not be committed.
Check before pushing:

```bash
git status --short
git check-ignore .env cloudflare-email-worker/.dev.vars
```

Commit and push the project. Render deploys from the repository, not from your
laptop.

## 3. Deploy the Python backend

### Render

1. Create a **New Web Service** and connect the GitHub repository.
2. Set the **Root Directory** to `RedLiner`.
3. Runtime: Python 3.12.
4. Build command:

   ```bash
   pip install uv && uv sync --frozen --python 3.12
   ```

5. Start command:

   ```bash
   PYTHONPATH=. .venv/bin/uvicorn server.app:app --host 0.0.0.0 --port $PORT
   ```

6. Add environment variables:

   ```text
   OPENCODE_API_KEY=...
   OPENCODE_MODEL=glm-5.3-flash
   EMAIL_PROVIDER=smtp
   SMTP_USER=...
   SMTP_PASSWORD=...
   SMTP_FROM=...
   REDLINER_WEBHOOK_TOKEN=<a long random value>
   MCP_ENABLED=true
   A2A_ENABLED=true
   A2A_VENDOR_URL=https://<your-a2a-host>
   RETENTION_DAYS=90
   # DATABASE_URL=postgresql://user:password@host:5432/postgres
   REVIEWER_EMAIL=reviewer@example.com
   ```

   The deal store defaults to `data/redliner_deals.db`. On a host with an
   ephemeral filesystem, attach a persistent disk and point
   `REDLINER_DB_PATH` there so approvals and deal history survive deploys.

   `CLOUDFLARE_WORKER_URL` and `CLOUDFLARE_DISPATCH_TOKEN` are not needed when
   using Direct SMTP. They are only used if outbound mail goes through the
   Worker instead.

7. Deploy and open `https://<service>.onrender.com`. Check `/api/health`.

Render’s free plan can sleep. A cold start can make the first inbound email
request slower than the Worker/email timeout. Use a paid instance for reliable
inbound processing, or keep the service warm during the demo.

The filesystem is usually ephemeral. Generated `.docx` files and
`data/email_config.json` may disappear on restart. SMTP values are re-seeded from
environment variables when the config file is recreated.

### Railway/Fly/VPS

Use the same build/start commands and environment variables. Expose HTTPS on a
public hostname. Cloudflare Email Routing requires an HTTPS URL, not a private
localhost address.

## 4. Optional A2A vendor agent

The A2A server is a separate ADK service:

```bash
cd RedLiner
PYTHONPATH=. uv run python -m uvicorn a2a_servers.vendor_agent:app \
  --host 0.0.0.0 --port 8001
```

For a hosted deployment, give it a public HTTPS URL, set `A2A_VENDOR_URL` on the
main backend and `A2A_ENABLED=true`. Do not expose it without authentication in a
real environment; the current implementation is local-trust only.

The review workbench is served at:

```text
https://<backend>/deals.html
```

Set `REVIEWER_EMAIL` and/or `REVIEWER_WEBHOOK_URL` to send review notifications.
The signed link is a convenience token; add authentication before exposing deal
data publicly.

Run retention:

```bash
PYTHONPATH=. uv run python scripts/purge_retention.py --days 90 --artifacts
```

## 5. Configure the Cloudflare Worker

In `cloudflare-email-worker/wrangler.toml`, change the webhook URL:

```toml
[vars]
REDLINER_WEBHOOK_URL = "https://<your-backend-host>/api/webhook/email"
```

Deploy it:

```bash
cd cloudflare-email-worker
npm ci
npx wrangler login
npx wrangler secret put REDLINER_WEBHOOK_TOKEN
# Paste the same value used in the backend environment.
npm run deploy
```

`REDLINER_WEBHOOK_TOKEN` is optional, but a public webhook without it can be
called by anyone. Set it in production.

If you want outbound mail to go through the Worker instead of Direct SMTP, also
set these Worker secrets:

```bash
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put DISPATCH_AUTH_TOKEN
```

The outbound Worker route uses Resend and requires a verified sender domain in
Resend. For Direct SMTP, skip these; the backend sends directly and Cloudflare is
only the inbound edge.

## 6. Configure Cloudflare Email Routing

If the domain already receives mail through Google Workspace, Microsoft 365 or
another provider, do **not** replace the apex MX records. Use a subdomain.

1. In Cloudflare, go to **Compute > Email Service > Email Routing**.
2. Select **Onboard Domain** and choose the domain.
3. Let Cloudflare create the MX, SPF and DKIM records. DNS normally propagates in
   5–15 minutes.
4. For a conflict-free address, open the domain’s **Settings > Subdomains** and
   add a subdomain such as `contracts`.
5. Open **Routing Rules** and create a rule:
   - Email pattern: `deals` at `contracts.yourdomain.com` (or your chosen
     address/domain)
   - Action: **Send to a Worker**
   - Worker: `redliner-email-worker`
6. Save the rule.

The rule sends the complete MIME message to the Worker. The Worker parses
attachments with `postal-mime` and posts the JSON to the backend.

## 7. Test inbound processing

Send from a **different** mailbox to the address in the routing rule. Attach a
`.docx` or `.pdf` contract.

Watch the Worker:

```bash
cd cloudflare-email-worker
npx wrangler tail redliner-email-worker
```

Watch the backend logs in Render. A successful request returns a processed deal
with `run_status`, `llm_status`, redline details and a draft. A message with no
`.docx`/`.pdf` attachment returns `RECEIVED` and is not processed.

For Direct SMTP, the backend does **not** automatically send the counter
proposal. Review the draft in the dashboard and dispatch it to the sender or to
your own address. This is the human approval step.

## 8. Send the reply

The inbound webhook stores the contract and returns the draft, but it does not
currently save a “reply to original sender” button. In the dashboard’s outbound
form, enter the vendor address (or your own email for a test), select the
redlined document, and dispatch. Because `EMAIL_PROVIDER=smtp`, the backend sends
through the SMTP account configured in the dashboard/`.env`.

## Local-only alternative: Cloudflare Tunnel

If you do not want to deploy the backend yet:

```bash
# Terminal 1
PYTHONPATH=. uv run python -m uvicorn server.app:app --host 127.0.0.1 --port 8000

# Terminal 2
cloudflared tunnel --url http://127.0.0.1:8000
```

Put the generated `https://...trycloudflare.com/api/webhook/email` into
`REDLINER_WEBHOOK_URL`, deploy the Worker, and create the Email Routing rule as
above. A quick tunnel URL changes when restarted, so redeploy the Worker whenever
it changes. This is suitable for a demo, not production.

## No-domain alternative: poll Gmail over IMAP

This avoids Cloudflare Email Routing, DNS, and a public webhook entirely. It uses
the same Gmail account and App Password already configured for Direct SMTP.

1. In Gmail, enable **Settings > Forwarding and POP/IMAP > Enable IMAP**.
2. Create a label named `RedLiner`. In **Settings > Labels**, open the label and
   enable **Show in IMAP**; otherwise IMAP cannot select the label. Apply the
   label to at least one message too.
3. Optional: use a Gmail plus-address such as
   `yourname+contracts@gmail.com`. It still delivers to your normal inbox and
   gives you a dedicated address without owning a domain.
4. Create a Gmail filter that applies that label to contract mail. For example:
   - Criteria: `to:(yourname+contracts@gmail.com) has:attachment`
   - Or: `has:attachment subject:(contract OR agreement OR proposal OR MSA)`
   - Action: **Apply the label: RedLiner**
   - Tick **Also apply filter to matching conversations** if you want existing
     mail included.
5. Start the backend locally or on a host. No inbound port or domain is needed.
6. Run the poller:

   ```bash
   cd RedLiner
   PYTHONPATH=. uv run python scripts/gmail_inbox_poller.py --interval 60
   ```

   It checks the `RedLiner` label every 60 seconds. It processes the first
   `.docx`/`.pdf` attachment in each unread message and marks processed mail as
   read. It does **not** send a reply automatically.

For a single manual check:

```bash
PYTHONPATH=. uv run python scripts/gmail_inbox_poller.py --once
```

You can run it in the foreground while demoing. For an always-on setup, run it
on the same machine/container as the backend (systemd, Termux, or a supervisor
process) so the dashboard can see generated files. A separate Render background
worker has its own filesystem; it would need shared storage or a change to POST
to the backend webhook. The poller writes processed runs to
`data/incoming/gmail_poller_runs.jsonl`.

Only poll `INBOX` if you accept that unread personal messages with attachments
may be processed:

```bash
PYTHONPATH=. uv run python scripts/gmail_inbox_poller.py --once --folder INBOX
```

The poller needs the SMTP username and App Password from
`data/email_config.json` (seeded from `SMTP_USER` / `SMTP_PASSWORD` on a fresh
deployment). It only creates a draft; send it from the dashboard after review.

### Which inbound option should I use?

| Situation | Option |
|---|---|
| You own a domain and can put its DNS on Cloudflare | Cloudflare Email Routing + Worker (best-looking, production-shaped) |
| You have no domain | Gmail IMAP poller (simplest; no Cloudflare needed) |
| You want to demo without deploying | Local backend + Cloudflare Tunnel + Worker, or Gmail IMAP poller |
| You already use Google Workspace/Gmail | Gmail IMAP poller avoids MX changes |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Test email says `cloudflare_mock_dispatcher` | The request used the Worker, not Direct SMTP. Set `EMAIL_PROVIDER=smtp` and select Direct SMTP in the dashboard. |
| SMTP test says authentication failed | Use a Google App Password, enable 2-Step Verification, and check the full Gmail address. |
| Inbound mail is delivered but nothing happens | Check the routing rule points at the deployed Worker; check `wrangler tail` and Render logs. |
| Worker returns 401 | `REDLINER_WEBHOOK_TOKEN` differs between the Worker secret and backend env. |
| Worker cannot reach backend | Use a public HTTPS URL; localhost is only reachable from a local Worker. Check for Render cold starts. |
| No attachment processed | Only `.docx` and `.pdf` are accepted. Check the Worker payload and backend logs. |
| Reply goes from the wrong address | Gmail sends from the authenticated account; configure a verified “Send mail as” alias or use a domain-verified Resend sender. |
| Webhook can be called publicly | Set `REDLINER_WEBHOOK_TOKEN` in both places and configure WAF/rate limiting for production. |

## Limits and security notes

- Cloudflare Email Routing inbound limit: 25 MiB per message, including
  attachments. Workers Free has CPU limits; complex parsing may fail with
  `EXCEEDED_CPU`. Use a paid Worker plan for larger contracts.
- A Cloudflare Worker is not a substitute for the FastAPI backend. It cannot run
  this project’s Python packages and SMTP stack.
- Never commit `.env`, `.dev.vars`, API keys or app passwords.
- Use Cloudflare Access, WAF rules or an API gateway in front of a public demo
  backend. The inbound webhook token only protects that one route.
- The current inbound flow processes an attachment and drafts a reply; it does not
  auto-send. Keep human approval for contract commitments.
