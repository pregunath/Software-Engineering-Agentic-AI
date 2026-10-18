"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "../../components/AppShell";
import {
  api,
  type ConnectedRepo,
  type GithubRemoteRepo,
  type Plan,
  type Task,
  type TaskEvent,
} from "../../lib/api";

export default function AgentPage() {
  const [githubLogin, setGithubLogin] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [remoteRepos, setRemoteRepos] = useState<GithubRemoteRepo[]>([]);
  const [connected, setConnected] = useState<ConnectedRepo[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [localPath, setLocalPath] = useState<string | null>(null);

  async function refreshGithub() {
    const status = await api.githubStatus();
    setGithubLogin(status.login);
    if (status.connected) {
      const [remotes, linked] = await Promise.all([api.listGithubRepos(), api.listConnectedRepos()]);
      setRemoteRepos(remotes);
      setConnected(linked);
      if (linked[0] && selectedRepoId === null) setSelectedRepoId(linked[0].id);
    }
  }

  useEffect(() => {
    void refreshGithub().catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!task) return;
    const source = new EventSource(`${api.baseUrl}/tasks/${task.id}/events/stream`);
    const refresh = () => {
      void api.events(task.id).then(setEvents).catch(() => undefined);
      void api
        .getPlan(task.id)
        .then(setPlan)
        .catch(() => undefined);
    };
    for (const name of ["task.status_changed", "task.cancelled", "task.recovered", "task.retry_accepted"]) {
      source.addEventListener(name, refresh);
    }
    refresh();
    return () => source.close();
  }, [task?.id]);

  async function connectGithub(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const status = await api.connectGithub(token.trim());
      setGithubLogin(status.login);
      setToken("");
      await refreshGithub();
    } catch (err) {
      setError(err instanceof Error ? err.message : "GitHub connect failed.");
    } finally {
      setBusy(false);
    }
  }

  async function linkRepo(fullName: string) {
    setBusy(true);
    setError(null);
    try {
      const repo = await api.connectGithubRepo(fullName);
      setConnected((current) => [repo, ...current.filter((item) => item.id !== repo.id)]);
      setSelectedRepoId(repo.id);
      setLocalPath(repo.local_path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clone repository.");
    } finally {
      setBusy(false);
    }
  }

  async function startTask(event: FormEvent) {
    event.preventDefault();
    if (!selectedRepoId || !prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createGithubTask(selectedRepoId, prompt.trim().slice(0, 80), prompt.trim());
      setTask(created);
      setLocalPath(created.local_path);
      const generated = await api.generatePlan(created.id, { workspace_path: created.local_path });
      setPlan(generated);
      setEvents(await api.events(created.id));
      setPrompt("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start agent task.");
    } finally {
      setBusy(false);
    }
  }

  async function approveAndRun() {
    if (!task || !localPath) return;
    setBusy(true);
    setError(null);
    try {
      setPlan(await api.approvePlan(task.id));
      const updated = await api.executeTask(task.id, localPath);
      setTask(updated);
      setEvents(await api.events(task.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Execution failed.");
    } finally {
      setBusy(false);
    }
  }

  const selected = connected.find((repo) => repo.id === selectedRepoId) ?? null;

  return (
    <AppShell mode="agent">
      <div className="agent-page">
        <header className="agent-header">
          <div>
            <p className="eyebrow">Agent mode</p>
            <h1>GitHub-powered tasks</h1>
            <p className="intro-copy">
              Connect GitHub, clone a repository onto the API host, then let Forge plan and apply changes with
              approval.
            </p>
          </div>
        </header>

        {error && <p className="workspace-error">{error}</p>}

        <div className="agent-grid">
          <section className="glass-card">
            <h2>1. Connect GitHub</h2>
            {githubLogin ? (
              <p className="panel-muted">
                Connected as <strong>{githubLogin}</strong>
              </p>
            ) : (
              <form onSubmit={connectGithub} className="stack-form">
                <label>
                  Personal access token
                  <input
                    value={token}
                    onChange={(event) => setToken(event.target.value)}
                    type="password"
                    required
                  />
                </label>
                <button className="btn" type="submit" disabled={busy}>
                  Connect
                </button>
                <small className="panel-muted">
                  Create a classic PAT with `repo` scope. The token is encrypted at rest and never sent to the LLM.
                </small>
              </form>
            )}

            {githubLogin && (
              <>
                <h3>Available repositories</h3>
                <div className="repo-pick-list">
                  {remoteRepos.slice(0, 30).map((repo) => (
                    <button
                      key={repo.full_name}
                      type="button"
                      className="repo-pick"
                      disabled={busy}
                      onClick={() => void linkRepo(repo.full_name)}
                    >
                      <strong>{repo.full_name}</strong>
                      <span>{repo.private ? "Private" : "Public"}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </section>

          <section className="glass-card">
            <h2>2. Create an agent task</h2>
            <label>
              Connected repo
              <select
                value={selectedRepoId ?? ""}
                onChange={(event) => setSelectedRepoId(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">Select a connected repo</option>
                {connected.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.full_name}
                  </option>
                ))}
              </select>
            </label>
            {selected?.local_path && <p className="panel-muted">Local clone: {selected.local_path}</p>}
            <form onSubmit={startTask} className="stack-form">
              <label>
                What should Forge do?
                <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} required />
              </label>
              <button className="btn" type="submit" disabled={busy || !selectedRepoId}>
                {busy ? "Working…" : "Start task"}
              </button>
            </form>

            {plan && (
              <div className="agent-plan">
                <h3>{plan.summary}</h3>
                <p>{plan.content}</p>
                {plan.proposed_diff && <pre className="diff-view">{plan.proposed_diff}</pre>}
                {plan.status === "awaiting_approval" && (
                  <button type="button" className="btn" disabled={busy} onClick={() => void approveAndRun()}>
                    Approve, apply &amp; test
                  </button>
                )}
              </div>
            )}

            {task && (
              <div className="agent-events">
                <h3>Status: {task.status}</h3>
                <ul>
                  {events.map((event) => (
                    <li key={event.id}>
                      <span>{event.type}</span>
                      <small>{event.payload}</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
