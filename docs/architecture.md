# Architecture

## Runtime boundary

The Next.js dashboard communicates with FastAPI over local HTTP. FastAPI owns task state, validation, persistence, and all future agent execution. Ollama is reached only through a small provider boundary so model selection does not leak into orchestration logic.

## Planned modules

- `api`: request validation and HTTP/SSE transport
- `services`: task lifecycle and approvals
- `agent`: bounded orchestration and state transitions
- `llm`: Ollama provider and structured model responses
- `tools`: explicit repository and editing tools
- `workspace`: disposable worktree/copy management
- `execution`: allowlisted commands and isolation policy
- `github`: optional REST integration
- `db`: SQLAlchemy models and repositories

## State model

Tasks will move through `queued`, `planning`, `awaiting_approval`, `executing`, `testing`, `needs_attention`, `completed`, `failed`, or `cancelled`. State transitions and events will be persisted before being emitted to SSE clients.

## Initial data flow

1. User submits a task in the dashboard.
2. FastAPI validates and persists it as `queued`.
3. A future worker will inspect a disposable workspace and ask Ollama for a structured plan.
4. The user approves the plan before modifications.
5. The worker applies bounded changes, runs approved tests, and stores results.
6. The dashboard renders the persisted state and reviewable diff.

## Repository inspection boundary

The current inspection API accepts an explicit local workspace path and exposes only bounded operations: file listing, file reads, text search, project configuration discovery, Git status, and Git diff. Paths are resolved beneath the workspace, symbolic links are rejected, common dependency/build directories are skipped, dotenv files are excluded, and output/file sizes are capped.

Before inspection or editing, `WorkspaceManager` creates a disposable copy under `.workspaces`. The copy excludes `.git`, dependencies, build outputs, and dotenv secrets, so the original repository is not a mutation target.
