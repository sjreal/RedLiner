# RedLiner diagrams

Editable Mermaid sources and rendered outputs. The Mermaid blocks in the docs
remain the primary editable source; these files are for GitHub previews, slides
and reports.

The layouts are portrait-oriented for document pages. Optional edge/TLS nodes
(Cloudflare/Caddy, Email Routing) and optional search providers (Tavily/Serper)
are omitted from the diagrams.

| Diagram | Mermaid source | SVG | PNG |
|---|---|---|---|
| System architecture | [architecture.mmd](architecture.mmd) | [SVG](architecture.svg) | [PNG](architecture.png) |
| Runtime split (ADK + CrewAI) | [runtime.mmd](runtime.mmd) | [SVG](runtime.svg) | [PNG](runtime.png) |
| AWS Compose deployment | [aws-deployment.mmd](aws-deployment.mmd) | [SVG](aws-deployment.svg) | [PNG](aws-deployment.png) |

## System architecture

![RedLiner system architecture](architecture.svg)

## Runtime split

![RedLiner ADK and CrewAI runtime](runtime.svg)

## AWS deployment topology

![AWS Lightsail Compose deployment](aws-deployment.svg)

## Regenerate

From the repository root:

```bash
./scripts/render_diagrams.sh
```

The script uses `npx @mermaid-js/mermaid-cli` and a local Chrome/Chromium. Set
`PUPPETEER_EXECUTABLE_PATH` if the browser is not found automatically.
