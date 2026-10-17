# Forge coding workspace

Forge is a standalone AI coding environment (Monaco editor + explorer + agent panel) backed by the FastAPI/Ollama stack.

## Opening a repository

1. Start the API on the machine that contains your projects.
2. In the toolbar, paste an absolute folder path (example: `C:\Users\You\project`).
3. Click **Open**. Forge registers that path in SQLite and loads the file tree.

Browsers cannot freely browse your disk. Registration only works when `AGENT_ALLOW_HOST_WORKSPACES=true` (default in local development). Keep it **false** on public cloud APIs.

## Editing

- Open files from the explorer (multi-tab Monaco).
- Save uses optimistic concurrency (`expected_content`). Stale saves return HTTP 409.
- Secrets and ignored paths (`.env*`, `node_modules`, etc.) stay hidden from listing/read APIs.

## Agent loop

1. Describe a change in the Agent panel (open file is included as bounded context).
2. Ollama generates a plan + unified diff.
3. Approve the plan.
4. **Apply & test** runs checkpointed patching and Docker-allowlisted tests on the registered root.
5. Disposable copies remain available via `POST /repos/{id}/agent-workspace` for isolated experiments.

## Git panel

Bottom **Git** tab shows `git status` / `git diff` for the registered root when `.git` exists. Forge does not auto-commit or push.
