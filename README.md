# Forge: AI Software Engineer Agent

Forge investigates coding tasks, creates an approval-gated plan, applies changes in an isolated workspace, runs approved tests, and presents a reviewable diff.

It runs **locally** for development and can deploy **globally** (Vercel frontend + Fly.io API + Ollama).

## Coding workspace

The UI is a standalone coding environment (explorer + Monaco + agent + git/test panel). See [docs/workspace.md](docs/workspace.md).

Register a project by pasting an **absolute path on the API host** (local mode). Browsers cannot browse your disk directly.

## Modes

| Mode | Frontend | API | LLM |
|---|---|---|---|
| Local | `localhost:3000` | `127.0.0.1:8000` | Ollama on this machine |
| Cloud | Vercel | Fly.io | Ollama companion app / host |

Cloud deploy steps: [docs/deploy.md](docs/deploy.md). Security notes: [docs/security.md](docs/security.md).

## Prerequisites

- Windows, macOS, or Linux
- Python 3.12 or 3.14
- Node.js 20+
- Ollama 0.40.5 or newer
- A local model, initially `gemma4:e2b`
- Docker (required for isolated test execution)

## Run locally

Start Ollama and optionally pull the initial model:

```powershell
ollama serve
ollama pull gemma4:e2b
```

Or use Compose:

```powershell
docker compose -f docker-compose.ollama.yml up -d
```

In another terminal:

```powershell
py -m pip install -e ".\\backend[dev]"
py -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In a third terminal:

```powershell
cd frontend
copy .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000. The dashboard calls same-origin `/api/forge/*`; the Next.js proxy forwards to `FORGE_API_UPSTREAM` (default `http://127.0.0.1:8000`) and injects `FORGE_API_KEY` when set.

API health: http://127.0.0.1:8000/health.

Copy [`.env.example`](.env.example) at the repo root for backend variables. See [frontend/.env.example](frontend/.env.example) for the dashboard proxy.

For automated tests and smoke checks, see [docs/testing-guide.md](docs/testing-guide.md).

## Cloud deploy (summary)

1. Deploy Ollama with [`fly.ollama.toml`](fly.ollama.toml)
2. Deploy the API with [`fly.toml`](fly.toml) + `/data` volume; set `AGENT_API_KEY` and `AGENT_CORS_ORIGINS`
3. Deploy `frontend/` on Vercel with `FORGE_API_UPSTREAM`, `FORGE_API_KEY`, and `NEXT_PUBLIC_API_BASE_URL=/api/forge`

Details: [docs/deploy.md](docs/deploy.md).

## Inference policy

Forge uses **Ollama** (self-hosted / local). Paid cloud LLM APIs are out of scope. Do not put repository secrets, GitHub tokens, or environment variables into model prompts.
