# Deployment options

| Option | Monthly cost | Backend | Gmail poller | A2A | Best for |
|---|---:|---|---|---|---|
| Render free + Supabase free + Langfuse free | $0 | ✅ | only while awake | separate free service | zero-cost demo |
| Render Starter + free external services | ~$7 | ✅ | ✅ | second service | simple hosted demo |
| **AWS Lightsail 1 GB all-in-one** | **~$5** | ✅ | ✅ | ✅ | cheapest reliable demo |
| AWS Lightsail 512 MB all-in-one | ~$3.50 | ✅ | ✅ | ✅ | tight-memory demo |
| AWS EC2 t4g.small | free trial/credits only | ✅ | ✅ | ✅ | if eligible, otherwise not cheap |
| Cloudflare Workers | $0 | ❌ Python/FastAPI not supported | — | — | email edge only |

The AWS all-in-one topology is diagrammed in
[`aws/README.md#deployment-topology`](aws/README.md#deployment-topology).

Recommended for the college demo:

- **Zero budget and tolerant of sleep:** Render free.
- **Cheapest reliable all-features:** AWS Lightsail 1 GB (~$5/month) with the
  `deploy/aws` Compose stack.
- **Do not** use Cloudflare Workers for the backend; they cannot run this Python
  FastAPI, CrewAI, ADK and SMTP stack.

External services in all options:

- Supabase Postgres: free tier.
- Langfuse Cloud: free tier.
- OpenCode Go: existing subscription/usage.
- Domain: optional; Gmail polling needs no domain.

No local runtime is required in any option.
