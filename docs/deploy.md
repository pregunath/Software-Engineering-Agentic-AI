# Deploying Forge (Vercel + Fly.io)

Forge splits into a public Next.js dashboard and a Docker-capable API that talks to Ollama.

```
Browser → Vercel (Next.js) → /api/forge proxy → Fly.io API → Ollama (+ Docker tests)
```

## Prerequisites

- Fly.io account and `fly` CLI
- Vercel account and project linked to `frontend/`
- A strong random `AGENT_API_KEY` / `FORGE_API_KEY` (same value)

## 1. Deploy Ollama

```bash
fly launch --config fly.ollama.toml --no-deploy
fly deploy --config fly.ollama.toml
fly ssh console -a forge-ollama -C "ollama pull gemma4:e2b"
```

Keep Ollama private when possible. Point the API at `http://forge-ollama.internal:11434`.

## 2. Deploy the API

```bash
fly volumes create forge_data --region iad --size 10
fly secrets set AGENT_API_KEY="your-long-random-secret" \
  AGENT_CORS_ORIGINS="https://your-app.vercel.app,http://localhost:3000"
fly deploy --config fly.toml
```

Confirm health:

```bash
curl https://forge-api.fly.dev/health
```

### Docker test isolation on Fly

Execution still requires the Docker CLI and a local engine (see `DockerCommandRunner`). Nested Docker is not enabled on standard Fly machines. If Docker is unavailable, execution fails closed (no host fallback). For full test isolation in production, run the API on a VM/host with Docker (or extend the image with a privileged Docker socket). Planning, approvals, and patching still work without Docker; only the test step fails closed.

SQLite and disposable workspaces live on the `/data` volume (`AGENT_DATABASE_URL=sqlite:////data/agent.db`).

## 3. Deploy the frontend (Vercel)

In the Vercel project for `frontend/`, set:

| Variable | Value |
|---|---|
| `FORGE_API_UPSTREAM` | `https://forge-api.fly.dev` |
| `FORGE_API_KEY` | same as `AGENT_API_KEY` |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/forge` |

Deploy. The browser only calls same-origin `/api/forge/*`; the Route Handler injects the Bearer token.

## Local cloud-shaped smoke

```bash
# API
set AGENT_ENVIRONMENT=production
set AGENT_API_KEY=dev-secret
set AGENT_API_HOST=0.0.0.0
py -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# Frontend
set FORGE_API_UPSTREAM=http://127.0.0.1:8000
set FORGE_API_KEY=dev-secret
set NEXT_PUBLIC_API_BASE_URL=/api/forge
cd frontend && npm run dev
```

## Security checklist

- HTTPS on both Vercel and Fly
- Non-empty `AGENT_API_KEY` in production
- CORS limited to your Vercel origin(s)
- Never put `AGENT_API_KEY` / `FORGE_API_KEY` in `NEXT_PUBLIC_*`
