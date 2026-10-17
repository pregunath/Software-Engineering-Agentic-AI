# Forge Testing Guide

This guide tests the local Forge application without cloud services or API keys.

## 1. Start the prerequisites

Open PowerShell and verify Ollama:

```powershell
$env:Path += ";$env:LOCALAPPDATA\Programs\Ollama"
ollama --version
ollama list
```

Make sure `gemma4:e2b` is installed. If it is missing:

```powershell
ollama pull gemma4:e2b
```

Verify Docker Desktop:

```powershell
docker version
```

The command must show both a Client and Server section.

## 2. Start the application

Use three terminals from the project root.

### Terminal A: Ollama

Ollama Desktop normally runs the local API automatically. Check it:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/version
```

If it is not running:

```powershell
ollama serve
```

### Terminal B: FastAPI

```powershell
py -m pip install -e ".\backend[dev]"
py -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### Terminal C: Next.js

```powershell
npm run dev --prefix frontend
```

Open the dashboard at http://localhost:3000.

## 3. Run the automated tests

From the project root:

```powershell
py -m pytest .\backend\tests -q
py -m compileall -q .\backend\app
```

A successful run currently reports all backend tests passing. Deprecation warnings from SQLAlchemy, pytest-asyncio, and Starlette do not indicate test failures.

Validate the frontend separately:

```powershell
Push-Location .\frontend
npx tsc --noEmit
npm run build
Pop-Location
```

## 4. Smoke-test the services

FastAPI health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Depth 5
```

Expected values include:

- `status`: `ok`
- `ollama.available`: `true`
- Ollama version: the installed local version

Frontend:

```powershell
(Invoke-WebRequest http://localhost:3000 -UseBasicParsing).StatusCode
```

Expected result: `200`.

## 5. Test the dashboard manually

1. Open http://localhost:3000.
2. Enter a task title and description.
3. Select **Queue investigation**.
4. Confirm the task appears in **Task history** with status `queued`.
5. Select the task row.
6. Confirm the detail panel appears with event history.
7. When a plan exists, confirm the plan summary, explanation, and proposed diff appear.
8. Confirm the approval control is visible only while the plan is awaiting approval.
9. Approve the plan and confirm the status changes to `executing` through the event stream.

The current dashboard does not yet create a plan automatically from the task form. To generate one, use the API endpoint in the next section.

## 6. Test local Ollama planning through the API

Create a task and keep its returned `id`:

```powershell
$task = Invoke-RestMethod http://127.0.0.1:8000/tasks -Method Post -ContentType "application/json" -Body (@{
  title = "Fix the parser"
  description = "Investigate the parser and add a focused regression test."
} | ConvertTo-Json)
$task
```

Generate a plan using a disposable repository workspace:

```powershell
$plan = Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($task.id)/plan/generate" -Method Post -ContentType "application/json" -Body (@{
  workspace_path = "C:\path\to\disposable\repository"
} | ConvertTo-Json)
$plan
```

The plan should have status `awaiting_approval`. The model must return structured JSON; malformed responses are rejected.

Approve it explicitly:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($task.id)/plan/approve" -Method Post
```

## 7. Test repository isolation and inspection

Create a disposable copy of a repository:

```powershell
$workspace = Invoke-RestMethod http://127.0.0.1:8000/workspaces -Method Post -ContentType "application/json" -Body (@{
  source_path = "C:\path\to\repository"
} | ConvertTo-Json)
$workspace
```

Inspect its files:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/inspection/files -Method Post -ContentType "application/json" -Body (@{
  workspace_path = $workspace.path
} | ConvertTo-Json)
```

Expected behavior:

- `.git`, `node_modules`, virtual environments, build outputs, and dotenv files are excluded.
- Paths outside the workspace are rejected.
- Symbolic links are rejected.
- Large files and outputs are bounded.

## 8. Test approved execution

After a plan is approved, execute it against the disposable workspace:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($task.id)/execute" -Method Post -ContentType "application/json" -Body (@{
  workspace_path = $workspace.path
} | ConvertTo-Json)
```

The execution path:

1. Applies the proposed unified diff with a checkpoint.
2. Detects approved test commands from project configuration.
3. Runs tests in Docker with no network access and resource limits.
4. Records test output as task events.
5. Finishes as `completed` or `needs_attention`.

Docker is required for this path. Forge will not silently fall back to unrestricted host execution.

## 9. Inspect event history and SSE output

JSON event history:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($task.id)/events"
```

SSE stream:

```powershell
curl.exe -N "http://127.0.0.1:8000/tasks/$($task.id)/events/stream"
```

Events should have increasing IDs and include lifecycle entries such as task creation, planning, approval, patch application, and test completion.

## Current limitations

- GitHub issue retrieval, commits, pushes, and pull requests are not implemented yet.
- The planner is bounded to one structured planning request; the full multi-step tool loop is still being expanded.
- Docker images must already be available locally because execution uses `--pull=never`.
- The current local database uses SQLite and is intended for development/testing.
