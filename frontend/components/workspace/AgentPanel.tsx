"use client";

import type { Plan, Task, TaskEvent } from "../../lib/api";

type Props = {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  onApprove: () => void;
  onRetry: () => void;
  onExecute: () => void;
  busy: boolean;
  task: Task | null;
  plan: Plan | null;
  events: TaskEvent[];
  openFilePath: string | null;
};

export function AgentPanel({
  prompt,
  onPromptChange,
  onSubmit,
  onCancel,
  onApprove,
  onRetry,
  onExecute,
  busy,
  task,
  plan,
  events,
  openFilePath,
}: Props) {
  const awaiting = plan?.status === "awaiting_approval" && task?.status === "awaiting_approval";
  const approved = plan?.status === "approved";
  const needsAttention = task?.status === "needs_attention";

  return (
    <aside className="agent-panel">
      <div className="side-heading">
        <h2>Agent</h2>
        {task && <span className={`status-badge status-${task.status}`}>{task.status.replaceAll("_", " ")}</span>}
      </div>
      {openFilePath && <p className="panel-muted">Context: {openFilePath}</p>}
      <textarea
        className="agent-input"
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
        rows={5}
        placeholder=""
        disabled={busy}
      />
      <div className="agent-actions">
        <button type="button" className="btn" onClick={onSubmit} disabled={busy || !prompt.trim()}>
          {busy ? "Working…" : "Ask Forge"}
        </button>
        {task && !["completed", "failed", "cancelled"].includes(task.status) && (
          <button type="button" className="btn btn-danger" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>

      {plan && (
        <div className="agent-plan">
          <h3>{plan.summary}</h3>
          <p>{plan.content}</p>
          {plan.proposed_diff && <pre className="diff-view">{plan.proposed_diff}</pre>}
          {awaiting && (
            <button type="button" className="btn" onClick={onApprove} disabled={busy}>
              Approve plan
            </button>
          )}
          {approved && task && !["testing", "completed", "cancelled"].includes(task.status) && (
            <button type="button" className="btn btn-secondary" onClick={onExecute} disabled={busy}>
              Apply &amp; test
            </button>
          )}
          {needsAttention && (
            <button type="button" className="btn btn-secondary" onClick={onRetry} disabled={busy}>
              Retry
            </button>
          )}
        </div>
      )}

      <div className="agent-events">
        <h3>Events</h3>
        {events.length === 0 ? (
          <p className="panel-muted">No events yet.</p>
        ) : (
          <ul>
            {events.map((event) => (
              <li key={event.id}>
                <span>{event.type}</span>
                <small>{event.payload}</small>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
