"use client";

import { FormEvent, useEffect, useState } from "react";

type Task = { id: number; title: string; description: string; status: string };
type Plan = { id: number; summary: string; content: string; proposed_diff: string; status: string };
type TaskEvent = { id: number; type: string; payload: string };

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/forge";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const CANCELLABLE_STATUSES = new Set([
  "queued",
  "planning",
  "awaiting_approval",
  "executing",
  "testing",
  "needs_attention",
]);

export default function Home() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadTasks();
  }, []);

  useEffect(() => {
    if (!selectedTask) return;
    const taskId = selectedTask.id;
    void loadTaskDetails(selectedTask);
    const source = new EventSource(`${apiBaseUrl}/tasks/${taskId}/events/stream`);

    const applyStatus = (status: string) => {
      setSelectedTask((current) => (current && current.id === taskId ? { ...current, status } : current));
      setTasks((current) => current.map((task) => (task.id === taskId ? { ...task, status } : task)));
    };

    const refreshEvents = () => {
      void fetch(`${apiBaseUrl}/tasks/${taskId}/events`)
        .then((response) => (response.ok ? response.json() : null))
        .then((loaded: TaskEvent[] | null) => {
          if (loaded) setEvents(loaded);
        });
    };

    for (const eventName of ["task.status_changed", "task.cancelled", "task.recovered", "task.retry_accepted"]) {
      source.addEventListener(eventName, (event) => {
        const payload = JSON.parse((event as MessageEvent).data) as { status?: string };
        if (payload.status) applyStatus(payload.status);
        refreshEvents();
      });
    }
    source.onerror = () => source.close();
    return () => source.close();
  }, [selectedTask?.id]);

  async function loadTasks() {
    try {
      const response = await fetch(`${apiBaseUrl}/tasks`);
      if (!response.ok) throw new Error("Could not load tasks.");
      const loaded: Task[] = await response.json();
      setTasks(loaded);
      if (loaded[0]) setSelectedTask(loaded[0]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not load tasks.");
    }
  }

  async function loadTaskDetails(task: Task) {
    const [planResponse, eventsResponse] = await Promise.all([
      fetch(`${apiBaseUrl}/tasks/${task.id}/plan`),
      fetch(`${apiBaseUrl}/tasks/${task.id}/events`),
    ]);
    setPlan(planResponse.ok ? await planResponse.json() : null);
    if (eventsResponse.ok) setEvents(await eventsResponse.json());
  }

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description }),
      });
      if (!response.ok) throw new Error("Could not create task.");
      const task: Task = await response.json();
      setTasks((current) => [task, ...current]);
      setSelectedTask(task);
      setTitle("");
      setDescription("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not create task.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function approvePlan() {
    if (!selectedTask || isCancelling || selectedTask.status === "cancelled") return;
    const response = await fetch(`${apiBaseUrl}/tasks/${selectedTask.id}/plan/approve`, { method: "POST" });
    if (!response.ok) {
      setError("Could not approve this plan.");
      return;
    }
    const refreshed = await fetch(`${apiBaseUrl}/tasks`);
    if (refreshed.ok) {
      const loaded: Task[] = await refreshed.json();
      setTasks(loaded);
      const updated = loaded.find((task) => task.id === selectedTask.id) ?? selectedTask;
      setSelectedTask(updated);
      await loadTaskDetails(updated);
    }
  }

  async function cancelTask() {
    if (!selectedTask || isCancelling) return;
    if (!CANCELLABLE_STATUSES.has(selectedTask.status)) return;
    setIsCancelling(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/tasks/${selectedTask.id}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error("Could not cancel this task.");
      const cancelled: Task = await response.json();
      setSelectedTask(cancelled);
      setTasks((current) => current.map((task) => (task.id === cancelled.id ? cancelled : task)));
      await loadTaskDetails(cancelled);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not cancel this task.");
    } finally {
      setIsCancelling(false);
    }
  }

  async function retryTask() {
    if (!selectedTask || isRetrying || selectedTask.status !== "needs_attention") return;
    setIsRetrying(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/tasks/${selectedTask.id}/retry`, { method: "POST" });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "Could not retry this task.");
      }
      const retried: Task = await response.json();
      setSelectedTask(retried);
      setTasks((current) => current.map((task) => (task.id === retried.id ? retried : task)));
      await loadTaskDetails(retried);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not retry this task.");
    } finally {
      setIsRetrying(false);
    }
  }

  const canCancel =
    !!selectedTask && CANCELLABLE_STATUSES.has(selectedTask.status) && !TERMINAL_STATUSES.has(selectedTask.status);
  const showRetry = selectedTask?.status === "needs_attention";
  const recoveryEvent = events.find((event) => event.type === "task.recovered");

  return (
    <>
      <div className="atmosphere" aria-hidden="true" />
      <main className="dashboard-shell">
        <header className="topbar">
          <div className="brand-lockup">
            <span className="brand-mark">F</span>
            <div>
              <p className="eyebrow">Software engineering agent</p>
              <h1 className="brand-name">Forge</h1>
            </div>
          </div>
          <div className="runtime-pill">
            <span className="status-dot" />
            <span>Cloud runtime</span>
          </div>
        </header>

        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">Investigate · plan · verify</p>
            <h2>Turn issues into verified changes.</h2>
            <p className="intro-copy">
              Queue a coding task, review an approval-gated plan, then let Forge patch and test in an isolated
              workspace.
            </p>
            <div className="cta-row">
              <span className="ghost-chip">Approval gated</span>
              <span className="ghost-chip">Isolated workspace</span>
              <span className="ghost-chip">Test verified</span>
            </div>
          </div>

          <form className="task-composer" onSubmit={createTask}>
            <div className="panel-heading">
              <div>
                <span className="step-number">01</span>
                <h3>Open a task</h3>
              </div>
              <span className="panel-caption">New investigation</span>
            </div>
            <label>
              Task title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Fix the failing parser"
                required
              />
            </label>
            <label>
              What needs attention?
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Describe the issue, expected behavior, and any useful clues."
                rows={5}
                required
              />
            </label>
            <button className="btn" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Queueing..." : "Queue investigation"}
              <span>↗</span>
            </button>
            {error && <p className="error-message">{error}</p>}
          </form>
        </section>

        <section className="activity-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Operations</p>
              <h2>Task history</h2>
            </div>
            <span className="count-badge">{tasks.length.toString().padStart(2, "0")} TASKS</span>
          </div>
          {tasks.length === 0 ? (
            <div className="empty-state">
              <span className="empty-glyph">+</span>
              <p>No investigations yet.</p>
              <small>Queued work appears here with live execution state.</small>
            </div>
          ) : (
            <div className="task-list">
              {tasks.map((task) => (
                <button
                  className={`task-select ${selectedTask?.id === task.id ? "selected" : ""}`}
                  key={task.id}
                  onClick={() => setSelectedTask(task)}
                  type="button"
                >
                  <div>
                    <span className="task-id">TASK-{String(task.id).padStart(4, "0")}</span>
                    <h3>{task.title}</h3>
                    <p>{task.description}</p>
                  </div>
                  <span className={`status-badge status-${task.status}`}>{task.status.replaceAll("_", " ")}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        {selectedTask && (
          <section className="detail-grid">
            <div className="detail-panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Selected task</p>
                  <h2>{selectedTask.title}</h2>
                </div>
                <span className={`status-badge status-${selectedTask.status}`}>
                  {selectedTask.status.replaceAll("_", " ")}
                </span>
              </div>
              {showRetry && (
                <div className="attention-banner">
                  <p>This task needs attention after an interruption or uncertain run.</p>
                  <small>
                    {recoveryEvent
                      ? recoveryEvent.payload
                      : "Review events and the disposable workspace before retrying. Partial patches are not repeated automatically."}
                  </small>
                </div>
              )}
              {plan ? (
                <>
                  <p className="plan-summary">{plan.summary}</p>
                  <p className="plan-content">{plan.content}</p>
                  {plan.proposed_diff && <pre className="diff-view">{plan.proposed_diff}</pre>}
                  {plan.status === "awaiting_approval" &&
                    selectedTask.status === "awaiting_approval" &&
                    !isCancelling && (
                      <button className="btn" onClick={approvePlan} disabled={isCancelling} type="button">
                        Approve plan <span>→</span>
                      </button>
                    )}
                </>
              ) : (
                <div className="waiting-state">
                  <p>Plan not available yet.</p>
                  <small>The agent publishes a plan here before any edit is authorized.</small>
                </div>
              )}
              {showRetry && (
                <button
                  className="btn btn-secondary"
                  onClick={retryTask}
                  disabled={isRetrying || isCancelling}
                  type="button"
                >
                  {isRetrying ? "Retrying..." : "Retry safe recovery"}
                  <span>↻</span>
                </button>
              )}
              {canCancel && (
                <button
                  className="btn btn-danger"
                  onClick={cancelTask}
                  disabled={isCancelling || isRetrying}
                  type="button"
                >
                  {isCancelling ? "Cancelling..." : "Cancel task"}
                  <span>×</span>
                </button>
              )}
            </div>
            <div className="detail-panel">
              <div className="panel-heading">
                <div>
                  <span className="step-number">LIVE</span>
                  <h3>Event history</h3>
                </div>
                <span className="panel-caption">SSE replay</span>
              </div>
              <div className="event-list">
                {events.map((event) => (
                  <div className="event-item" key={event.id}>
                    <span className="event-dot" />
                    <div>
                      <span className="task-id">
                        #{event.id} / {event.type}
                      </span>
                      <p>{event.payload}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
      </main>
    </>
  );
}
