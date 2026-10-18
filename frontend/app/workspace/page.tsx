"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentPanel } from "../../components/workspace/AgentPanel";
import { CodeEditor } from "../../components/workspace/CodeEditor";
import { FileTree } from "../../components/workspace/FileTree";
import { api, type Plan, type Repo, type Task, type TaskEvent, type TreeNode } from "../../lib/api";

type TabState = {
  path: string;
  content: string;
  savedContent: string;
};

type BottomTab = "problems" | "tests" | "agent" | "git";

export default function Home() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [activeRepoId, setActiveRepoId] = useState<number | null>(null);
  const [registerPath, setRegisterPath] = useState("");
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [tabs, setTabs] = useState<TabState[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [branch, setBranch] = useState<string>("—");
  const [gitStatus, setGitStatus] = useState("");
  const [gitDiff, setGitDiff] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [hostEnabled, setHostEnabled] = useState(true);
  const [capabilityNote, setCapabilityNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [bottomTab, setBottomTab] = useState<BottomTab>("agent");
  const [agentLog, setAgentLog] = useState("Ready.");

  const activeRepo = repos.find((repo) => repo.id === activeRepoId) ?? null;
  const activeTab = tabs.find((tab) => tab.path === activePath) ?? null;
  const dirty = !!activeTab && activeTab.content !== activeTab.savedContent;

  const filteredTree = useMemo(() => {
    if (!filter.trim()) return tree;
    const query = filter.trim().toLowerCase();
    const filterNodes = (nodes: TreeNode[]): TreeNode[] =>
      nodes
        .map((node) => {
          if (node.type === "file") {
            return node.path.toLowerCase().includes(query) ? node : null;
          }
          const children = filterNodes(node.children ?? []);
          if (children.length === 0 && !node.name.toLowerCase().includes(query)) return null;
          return { ...node, children };
        })
        .filter((node): node is TreeNode => node !== null);
    return filterNodes(tree);
  }, [filter, tree]);

  const refreshRepos = useCallback(async () => {
    const [caps, listed] = await Promise.all([api.capabilities(), api.listRepos()]);
    setHostEnabled(caps.host_workspaces_enabled);
    setCapabilityNote(caps.note);
    setRepos(listed);
    if (listed.length && activeRepoId === null) setActiveRepoId(listed[0].id);
  }, [activeRepoId]);

  const refreshTree = useCallback(async (repoId: number) => {
    const data = await api.tree(repoId);
    setTree(data.tree);
  }, []);

  const refreshGit = useCallback(async (repoId: number) => {
    try {
      const status = await api.gitStatus(repoId);
      setBranch(status.branch || "—");
      setGitStatus(status.status || "(clean)");
      const diff = await api.gitDiff(repoId);
      setGitDiff(diff.diff || "");
    } catch {
      setBranch("no git");
      setGitStatus("Git unavailable for this folder.");
      setGitDiff("");
    }
  }, []);

  useEffect(() => {
    void refreshRepos().catch((err: Error) => setError(err.message));
  }, [refreshRepos]);

  useEffect(() => {
    if (activeRepoId === null) return;
    void refreshTree(activeRepoId).catch((err: Error) => setError(err.message));
    void refreshGit(activeRepoId);
  }, [activeRepoId, refreshTree, refreshGit]);

  useEffect(() => {
    if (!task) return;
    const source = new EventSource(`${api.baseUrl}/tasks/${task.id}/events/stream`);
    const refresh = () => {
      void api.events(task.id).then(setEvents).catch(() => undefined);
      void api.listTasks().then((tasks) => {
        const updated = tasks.find((item) => item.id === task.id);
        if (updated) setTask(updated);
      });
      void api
        .getPlan(task.id)
        .then(setPlan)
        .catch(() => undefined);
    };
    for (const name of ["task.status_changed", "task.cancelled", "task.recovered", "task.retry_accepted"]) {
      source.addEventListener(name, refresh);
    }
    source.onerror = () => source.close();
    refresh();
    return () => source.close();
  }, [task?.id]);

  async function registerRepo() {
    if (!registerPath.trim()) return;
    setError(null);
    try {
      const repo = await api.registerRepo(registerPath.trim());
      setRegisterPath("");
      await refreshRepos();
      setActiveRepoId(repo.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not register repository.");
    }
  }

  async function openFile(path: string) {
    if (!activeRepo) return;
    const existing = tabs.find((tab) => tab.path === path);
    if (existing) {
      setActivePath(path);
      return;
    }
    try {
      const file = await api.readFile(activeRepo.id, path);
      setTabs((current) => [...current, { path, content: file.content, savedContent: file.content }]);
      setActivePath(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open file.");
    }
  }

  function updateActiveContent(content: string) {
    if (!activePath) return;
    setTabs((current) => current.map((tab) => (tab.path === activePath ? { ...tab, content } : tab)));
  }

  async function saveActive() {
    if (!activeRepo || !activeTab) return;
    setError(null);
    try {
      await api.writeFile(activeRepo.id, activeTab.path, activeTab.content, activeTab.savedContent);
      setTabs((current) =>
        current.map((tab) =>
          tab.path === activeTab.path ? { ...tab, savedContent: tab.content } : tab,
        ),
      );
      await refreshGit(activeRepo.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save file.");
    }
  }

  function closeTab(path: string) {
    const tab = tabs.find((item) => item.path === path);
    if (tab && tab.content !== tab.savedContent) {
      const ok = window.confirm(`${path} has unsaved changes. Close anyway?`);
      if (!ok) return;
    }
    setTabs((current) => current.filter((item) => item.path !== path));
    if (activePath === path) {
      const remaining = tabs.filter((item) => item.path !== path);
      setActivePath(remaining[remaining.length - 1]?.path ?? null);
    }
  }

  async function runAgent() {
    if (!activeRepo || !prompt.trim()) return;
    setBusy(true);
    setError(null);
    setBottomTab("agent");
    setAgentLog("Creating task and generating plan…");
    try {
      const created = await api.createTask(
        prompt.trim().slice(0, 80),
        prompt.trim(),
        activeRepo.id,
      );
      setTask(created);
      // Plan against the registered host root so open-file context matches the editor.
      const generated = await api.generatePlan(created.id, {
        workspace_path: activeRepo.root_path,
        open_file_path: activePath ?? undefined,
      });
      setPlan(generated);
      setEvents(await api.events(created.id));
      setAgentLog("Plan ready for review.");
      setPrompt("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent request failed.");
      setAgentLog("Agent request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function approvePlan() {
    if (!task) return;
    setBusy(true);
    try {
      const approved = await api.approvePlan(task.id);
      setPlan(approved);
      setAgentLog("Plan approved. Ready to apply & test.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve plan.");
    } finally {
      setBusy(false);
    }
  }

  async function executePlan() {
    if (!task || !activeRepo) return;
    setBusy(true);
    setBottomTab("tests");
    setAgentLog("Applying patch and running tests…");
    try {
      // Apply + test on the registered root so editor tabs refresh against the same files.
      // Disposable copies remain available via POST /repos/{id}/agent-workspace for isolated runs.
      const updated = await api.executeTask(task.id, activeRepo.root_path);
      setTask(updated);
      setEvents(await api.events(task.id));
      setAgentLog(`Execution finished: ${updated.status}`);
      await refreshTree(activeRepo.id);
      for (const tab of tabs) {
        try {
          const file = await api.readFile(activeRepo.id, tab.path);
          setTabs((current) =>
            current.map((item) =>
              item.path === tab.path
                ? item.content === item.savedContent
                  ? { ...item, content: file.content, savedContent: file.content }
                  : item
                : item,
            ),
          );
        } catch {
          /* ignore missing */
        }
      }
      await refreshGit(activeRepo.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Execution failed.");
      setAgentLog("Execution failed.");
    } finally {
      setBusy(false);
    }
  }

  async function cancelTask() {
    if (!task) return;
    setBusy(true);
    try {
      setTask(await api.cancelTask(task.id));
      setAgentLog("Task cancelled.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel.");
    } finally {
      setBusy(false);
    }
  }

  async function retryTask() {
    if (!task) return;
    setBusy(true);
    try {
      setTask(await api.retryTask(task.id));
      setAgentLog("Retry accepted.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not retry.");
    } finally {
      setBusy(false);
    }
  }

  const bottomContent = (() => {
    if (bottomTab === "git") return gitDiff || gitStatus || "No git output.";
    if (bottomTab === "tests") return agentLog;
    if (bottomTab === "problems") return error || "No problems.";
    return events.map((event) => `#${event.id} ${event.type}\n${event.payload}`).join("\n\n") || agentLog;
  })();

  return (
    <div className="workspace-app">
      <header className="workspace-toolbar">
        <div className="workspace-brand">
          <span className="brand-mark">F</span>
          <strong>Forge</strong>
        </div>
        <div className="toolbar-center">
          <select
            className="repo-select"
            value={activeRepoId ?? ""}
            onChange={(event) => setActiveRepoId(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">Select workspace</option>
            {repos.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
          {hostEnabled ? (
            <>
              <input
                className="repo-path-input"
                value={registerPath}
                onChange={(event) => setRegisterPath(event.target.value)}
                aria-label="Repository path"
              />
              <button type="button" className="btn toolbar-btn" onClick={() => void registerRepo()}>
                Open
              </button>
            </>
          ) : (
            <span className="panel-muted">{capabilityNote}</span>
          )}
        </div>
        <div className="toolbar-actions">
          <span className="git-pill">{branch}</span>
          <span className="agent-pill">
            <span className="status-dot" />
            {busy ? "Agent busy" : "Idle"}
          </span>
        </div>
      </header>

      {error && <p className="workspace-error">{error}</p>}

      <div className="workspace-main">
        <aside className="explorer-pane">
          <div className="side-heading" style={{ padding: "10px 12px 0" }}>
            <h2>Explorer</h2>
          </div>
          <div className="explorer-tools">
            <input value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter files" />
            <button
              type="button"
              className="btn toolbar-btn btn-secondary"
              onClick={() => activeRepoId && void refreshTree(activeRepoId)}
            >
              ↻
            </button>
          </div>
          {activeRepo ? (
            <FileTree nodes={filteredTree} selectedPath={activePath} onOpen={(path) => void openFile(path)} />
          ) : (
            <p className="panel-muted">Register a local folder path on the API host to begin.</p>
          )}
        </aside>

        <section className="editor-pane">
          <div className="editor-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.path}
                type="button"
                className={`editor-tab ${tab.path === activePath ? "active" : ""}`}
                onClick={() => setActivePath(tab.path)}
              >
                <span>
                  {tab.path.split("/").pop()}
                  {tab.content !== tab.savedContent ? <span className="dirty"> •</span> : null}
                </span>
                <span
                  onClick={(event) => {
                    event.stopPropagation();
                    closeTab(tab.path);
                  }}
                >
                  ×
                </span>
              </button>
            ))}
          </div>
          <div className="editor-body">
            <CodeEditor
              path={activePath}
              value={activeTab?.content ?? ""}
              onChange={updateActiveContent}
            />
          </div>
          <div className="editor-actions">
            <button type="button" className="btn toolbar-btn" onClick={() => void saveActive()} disabled={!dirty}>
              Save
            </button>
            <button
              type="button"
              className="btn toolbar-btn btn-secondary"
              disabled={!dirty || !activeTab}
              onClick={() => {
                if (!activeTab) return;
                setTabs((current) =>
                  current.map((tab) =>
                    tab.path === activeTab.path ? { ...tab, content: tab.savedContent } : tab,
                  ),
                );
              }}
            >
              Discard
            </button>
          </div>
        </section>

        <AgentPanel
          prompt={prompt}
          onPromptChange={setPrompt}
          onSubmit={() => void runAgent()}
          onCancel={() => void cancelTask()}
          onApprove={() => void approvePlan()}
          onExecute={() => void executePlan()}
          onRetry={() => void retryTask()}
          busy={busy}
          task={task}
          plan={plan}
          events={events}
          openFilePath={activePath}
        />
      </div>

      <section className="bottom-panel">
        <div className="bottom-tabs">
          {(
            [
              ["problems", "Problems"],
              ["tests", "Test Results"],
              ["agent", "Agent Output"],
              ["git", "Git"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`bottom-tab ${bottomTab === id ? "active" : ""}`}
              onClick={() => setBottomTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="bottom-body">{bottomContent}</div>
      </section>
    </div>
  );
}
