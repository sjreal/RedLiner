# Render — zero-cost demo deployment

Use `render.yaml` at the repository root for the backend. Render's free web
service can host:

- FastAPI API
- dashboard
- Gmail IMAP poller (while awake)
- report/deal endpoints
- Gmail SMTP outbound

It **does not** host the separate ADK A2A service on the same port. Options:

1. Deploy a second Render web service for A2A.
2. Run the all-in-one AWS Lightsail setup from `deploy/aws/`.
3. Disable A2A for the free Render-only demo.

## Backend

1. Push the repo to GitHub.
2. Render → **New → Blueprint** → select the repo.
3. `render.yaml` creates `redliner-api` as a Docker service.
4. Fill the `sync: false` values in the dashboard:
   - `DATABASE_URL` (Supabase)
   - `OPENCODE_API_KEY`
   - `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
   - `DEMO_PASSWORD`
   - `REVIEWER_EMAIL`
   - `A2A_VENDOR_URL`, `A2A_SERVICE_TOKEN` if running A2A
   - Langfuse keys
5. Deploy and open the service URL. Basic Auth prompts for `demo` and the password.

## A2A second service

Create another Render Web Service from the same Dockerfile:

```text
Docker command:
PYTHONPATH=. .venv/bin/uvicorn a2a_servers.vendor_agent:app --host 0.0.0.0 --port $PORT
```

Set:

```dotenv
A2A_HOST=<a2a-service>.onrender.com
A2A_PORT=443
A2A_PROTOCOL=https
A2A_SERVICE_TOKEN=<same token as backend>
```

Set the backend's `A2A_VENDOR_URL` to `https://<a2a-service>.onrender.com`.

## Free-tier caveats

- Render free services spin down after inactivity. The Gmail poller runs only
  while the service is awake.
- A free cron ping (e.g. cron-job.org) can keep one service warm.
- The free allowance is finite; two always-awake services may exceed it.
- A2A cold starts can exceed a short client timeout; set
  `A2A_TIMEOUT_SECONDS=60`.
- Use the AWS all-in-one option if you need reliable always-on processing.

## Minimum free configuration

For a pure free demo without A2A hosting:

```dotenv
A2A_ENABLED=false
GMAIL_POLL_ENABLED=true
```

The rest of the app works; use the Gmail label/poller path for incoming mail.
