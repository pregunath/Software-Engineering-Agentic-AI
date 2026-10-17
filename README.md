# Forge: Local AI Software Engineer Agent

Forge is a local-first software engineering agent. It will investigate coding tasks, create an approval-gated plan, make changes in an isolated workspace, run approved tests, and present a reviewable diff.

## Current status

Phases 1 and 2 are implemented:

- FastAPI backend with environment-based configuration
- SQLite task persistence through SQLAlchemy
- Ollama availability and version health check
- Task creation and history API
- Next.js dashboard shell wired to the task API
- Local-only default configuration
- Disposable repository copies with bounded, safe inspection tools
- Ollama model capability discovery and chat provider boundary
- Validated task state transitions persisted through the API

The bounded planning loop, approval records, patching, execution sandbox, SSE events, GitHub integration, and evaluation benchmarks are planned next.

## Prerequisites

- Windows, macOS, or Linux
- Python 3.12 or 3.14
- Node.js 20+
- Ollama 0.40.5 or newer
- A local model, initially `gemma4:e2b`

On this development machine Ollama is installed with an NVIDIA RTX A2000 Laptop GPU (8 GB VRAM) and 15.7 GB system memory. The initial model is a reasonable local starting point; larger models may be slow or spill into system memory.

## Run locally

Start Ollama and optionally pull the initial model:

```powershell
ollama serve
ollama pull gemma4:e2b
```

In another terminal:

```powershell
py -m pip install -e ".\\backend[dev]"
py -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In a third terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The API health endpoint is http://127.0.0.1:8000/health.

For a step-by-step manual covering automated tests, smoke checks, dashboard workflows, planning, SSE events, and Docker execution, see [docs/testing-guide.md](docs/testing-guide.md).

## Local-only policy

Forge does not use paid LLM APIs or cloud inference. It calls Ollama at `http://localhost:11434` by default. Cloud models and API keys are intentionally out of scope for this project.

Do not put repository content, GitHub tokens, or environment variables into model prompts. Future GitHub functionality will be optional and approval-gated.
