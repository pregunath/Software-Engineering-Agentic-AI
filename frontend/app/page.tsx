"use client";

import { FormEvent, useEffect, useState } from "react";

type Task = { id: number; title: string; description: string; status: string };
type Plan = { id: number; summary: string; content: string; proposed_diff: string; status: string };
type TaskEvent = { id: number; type: string; payload: string };

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export default function Home() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void loadTasks(); }, []);

  useEffect(() => {
    if (!selectedTask) return;
    void loadTaskDetails(selectedTask);
    const source = new EventSource(`${apiBaseUrl}/tasks/${selectedTask.id}/events/stream`);
    source.addEventListener("task.status_changed", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { status?: string };
      if (!payload.status) return;
      setSelectedTask((current) => current ? { ...current, status: payload.status! } : current);
      setTasks((current) => current.map((task) => task.id === selectedTask.id ? { ...task, status: payload.status! } : task));
    });
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
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Could not load tasks."); }
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
    event.preventDefault(); setIsSubmitting(true); setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, description }) });
      if (!response.ok) throw new Error("Could not create task.");
      const task: Task = await response.json();
      setTasks((current) => [task, ...current]); setSelectedTask(task); setTitle(""); setDescription("");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Could not create task."); }
    finally { setIsSubmitting(false); }
  }

  async function approvePlan() {
    if (!selectedTask) return;
    const response = await fetch(`${apiBaseUrl}/tasks/${selectedTask.id}/plan/approve`, { method: "POST" });
    if (!response.ok) { setError("Could not approve this plan."); return; }
    await loadTaskDetails(selectedTask);
  }

  async function cancelTask() {
    if (!selectedTask) return;
    setIsCancelling(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/tasks/${selectedTask.id}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error("Could not cancel this task.");
      const cancelled: Task = await response.json();
      setSelectedTask(cancelled);
      setTasks((current) => current.map((task) => task.id === cancelled.id ? cancelled : task));
      await loadTaskDetails(cancelled);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not cancel this task.");
    } finally {
      setIsCancelling(false);
    }
  }

  return (
    <main className="dashboard-shell">
      <header className="topbar"><div className="brand-lockup"><span className="brand-mark">F</span><div><p className="eyebrow">LOCAL ENGINEERING SYSTEM</p><h1>Forge</h1></div></div><div className="runtime-pill"><span className="status-dot" /> Ollama local runtime</div></header>
      <section className="hero-grid"><div className="intro-panel"><p className="eyebrow accent">WORKSPACE / 001</p><h2>Turn issues into verified changes.</h2><p className="intro-copy">A controlled software engineer agent that investigates repositories, proposes a plan, and earns permission before it edits.</p><div className="signal-row"><span>LOCAL INFERENCE</span><span>APPROVAL GATED</span><span>TEST VERIFIED</span></div></div>
        <form className="task-composer" onSubmit={createTask}><div className="panel-heading"><div><span className="step-number">01</span><h3>Open a task</h3></div><span className="panel-caption">NEW INVESTIGATION</span></div><label>Task title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Fix the failing parser" required /></label><label>What needs attention?<textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the issue, expected behavior, and any useful clues." rows={5} required /></label><button type="submit" disabled={isSubmitting}>{isSubmitting ? "Queueing..." : "Queue investigation"}<span>↗</span></button>{error && <p className="error-message">{error}</p>}</form>
      </section>
      <section className="activity-section"><div className="section-heading"><div><p className="eyebrow">OPERATIONS</p><h2>Task history</h2></div><span className="count-badge">{tasks.length.toString().padStart(2, "0")} TASKS</span></div>{tasks.length === 0 ? <div className="empty-state"><span className="empty-glyph">+</span><p>No investigations yet.</p><small>Your queued work will appear here with live execution state.</small></div> : <div className="task-list">{tasks.map((task) => <button className={`task-row task-select ${selectedTask?.id === task.id ? "selected" : ""}`} key={task.id} onClick={() => setSelectedTask(task)}><div><span className="task-id">TASK-{String(task.id).padStart(4, "0")}</span><h3>{task.title}</h3><p>{task.description}</p></div><span className={`status-badge status-${task.status}`}>{task.status.replaceAll("_", " ")}</span></button>)}</div>}</section>
      {selectedTask && <section className="detail-grid"><div className="detail-panel"><div className="section-heading"><div><p className="eyebrow">SELECTED TASK</p><h2>{selectedTask.title}</h2></div><span className={`status-badge status-${selectedTask.status}`}>{selectedTask.status.replaceAll("_", " ")}</span></div>{plan ? <><p className="plan-summary">{plan.summary}</p><p className="plan-content">{plan.content}</p>{plan.proposed_diff && <pre className="diff-view">{plan.proposed_diff}</pre>}{plan.status === "awaiting_approval" && <button onClick={approvePlan}>Approve plan <span>→</span></button>}</> : <div className="waiting-state"><p>Plan not available yet.</p><small>The agent will publish a plan here before any edit is authorized.</small></div>}{!["completed", "failed", "cancelled"].includes(selectedTask.status) && <button className="cancel-button" onClick={cancelTask} disabled={isCancelling}>{isCancelling ? "Cancelling..." : "Cancel task"}<span>×</span></button>}</div><div className="detail-panel event-panel"><div className="panel-heading"><div><span className="step-number">LIVE</span><h3>Event history</h3></div><span className="panel-caption">SSE REPLAY</span></div><div className="event-list">{events.map((event) => <div className="event-item" key={event.id}><span className="event-dot" /><div><span className="task-id">#{event.id} / {event.type}</span><p>{event.payload}</p></div></div>)}</div></div></section>}
    </main>
  );
}
