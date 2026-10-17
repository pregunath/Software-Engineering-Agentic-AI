# Security Notes

Forge treats repository files, issue text, README instructions, source comments, and generated model output as untrusted data.

## Controls

- API binds to `127.0.0.1` by default.
- CORS permits only the local frontend origins.
- The initial API has no GitHub credentials and no cloud LLM fallback.
- Future file tools must resolve paths beneath a designated workspace and reject traversal and unsafe symlink targets.
- Future command execution must use an explicit allowlist, timeouts, output limits, and preferably Docker isolation.
- Current command execution rejects commands outside the approved test-command allowlist, runs without a shell, and caps output.
- Current file changes require expected pre-edit content and create a recoverable checkpoint before writing.
- Unified diffs are restricted to same-file modifications, validated against current contents, and applied through the checkpointed editor.
- Test detection returns only fixed commands such as `python -m pytest` and `npm run test`; package script contents are never executed directly.
- Docker execution is configured with no network, bounded CPU/memory/process resources, a read-only container filesystem, and no image pull. If Docker is unavailable, execution fails rather than falling back to the host.
- Installation scripts and arbitrary shell commands must not run automatically.
- Repository changes must occur in a disposable copy or Git worktree, never directly in the user's original repository.
- Model output must be validated as structured tool requests before execution.
- Secrets must be redacted from logs and never included in Ollama prompts.

Docker is an additional isolation layer, not a complete security boundary for hostile code. The agent must remain approval-gated and bounded even when Docker is available. Prompt instructions cannot make untrusted code safe by themselves.
