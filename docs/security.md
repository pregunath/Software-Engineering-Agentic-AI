# Security Notes

Forge treats repository files, issue text, README instructions, source comments, and generated model output as untrusted data.

## Controls

### Network and access

- API binds to `127.0.0.1` by default for local development; production (Fly) binds `0.0.0.0` behind HTTPS.
- CORS origins come from `AGENT_CORS_ORIGINS` (comma-separated). Defaults to local Next.js origins.
- When `AGENT_API_KEY` is set, protected routes require `Authorization: Bearer <key>`. In `AGENT_ENVIRONMENT=production`, a missing key returns `503` on protected routes.
- Public health endpoints (`/health`, `/health/database`) stay open for probes.
- The Vercel/Next dashboard should call same-origin `/api/forge/*`. The Route Handler injects `FORGE_API_KEY` server-side so the browser never holds the API secret. Never put the key in `NEXT_PUBLIC_*`.

### Execution and data

- The API has no GitHub credentials and no paid cloud LLM fallback (Ollama only).
- File tools resolve paths beneath a designated workspace and reject traversal and unsafe symlink targets.
- Command execution uses an explicit allowlist, timeouts, output limits, and Docker isolation.
- Command execution rejects commands outside the approved test-command allowlist, runs without a shell, and caps output.
- File changes require expected pre-edit content and create a recoverable checkpoint before writing.
- Unified diffs are restricted to same-file modifications, validated against current contents, and applied through the checkpointed editor.
- Test detection returns only fixed commands such as `python -m pytest` and `npm run test`; package script contents are never executed directly.
- Docker execution is configured with no network, bounded CPU/memory/process resources, a read-only container filesystem, and no image pull. If Docker is unavailable, execution fails rather than falling back to the host.
- Installation scripts and arbitrary shell commands must not run automatically.
- Repository changes must occur in a disposable copy or Git worktree, never directly in the user's original repository.
- Model output must be validated as structured tool requests before execution.
- Secrets must be redacted from logs and never included in Ollama prompts.

### Cloud notes

- Prefer HTTPS on both Vercel and Fly.
- Restrict `AGENT_CORS_ORIGINS` to your production frontend origin(s).
- Nested Docker on managed PaaS may be unavailable; Forge fails closed instead of running tests on the host. See [deploy.md](deploy.md).

Docker is an additional isolation layer, not a complete security boundary for hostile code. The agent must remain approval-gated and bounded even when Docker is available. Prompt instructions cannot make untrusted code safe by themselves.
