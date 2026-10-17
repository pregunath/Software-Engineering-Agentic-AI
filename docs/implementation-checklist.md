# Implementation Checklist

## Phase 1: foundation

- [x] FastAPI application and environment configuration
- [x] SQLite task model and persistence
- [x] Ollama health/version check
- [x] Task creation and listing API
- [x] Next.js dashboard shell
- [x] Local-only README and security notes

## Phase 2: next

- [x] Add disposable workspace creation
- [x] Implement `.gitignore`-aware inspection tools
- [x] Add bounded file search, configuration, and Git inspection endpoints
- [x] Add injectable Ollama provider with model capability discovery and chat handling
- [x] Add validated, persisted task state transitions
- [x] Add structured Ollama provider calls and model capability checks
- [x] Add persisted agent state transitions
- [x] Add persisted plan approvals
- [x] Add task plan and proposed-diff API
- [x] Add dashboard task selection, plan review, and approval controls
- [x] Add dashboard SSE consumption and event history
- [x] Add bounded Ollama planning and structured plan persistence
- [x] Execute approved diffs and detected tests through the isolated execution path
- [x] Add checkpointed file changes with stale-content validation and rollback
- [x] Add bounded command execution with an explicit test-command allowlist
- [x] Detect fixed test commands from project configuration without executing script text
- [x] Add persisted task lifecycle events and SSE replay
- [x] Add unified-diff validation/application
- [x] Add Docker-backed execution isolation with no host fallback
