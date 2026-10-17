const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/forge";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type Repo = {
  id: number;
  name: string;
  root_path: string;
  agent_workspace_path: string | null;
  host_workspaces_enabled: boolean;
};

export type TreeNode = {
  name: string;
  path: string;
  type: "file" | "directory";
  children?: TreeNode[];
};

export type Task = { id: number; title: string; description: string; status: string; workspace_id?: number | null };
export type Plan = {
  id: number;
  summary: string;
  content: string;
  proposed_diff: string;
  status: string;
};
export type TaskEvent = { id: number; type: string; payload: string };

export const api = {
  baseUrl: apiBaseUrl,
  capabilities: () => request<{ host_workspaces_enabled: boolean; note: string }>("/repos/capabilities"),
  listRepos: () => request<Repo[]>("/repos"),
  registerRepo: (path: string, name?: string) =>
    request<Repo>("/repos", { method: "POST", body: JSON.stringify({ path, name }) }),
  deleteRepo: (id: number) => request<void>(`/repos/${id}`, { method: "DELETE" }),
  tree: (id: number) => request<{ files: string[]; tree: TreeNode[] }>(`/repos/${id}/tree`),
  readFile: (id: number, path: string) =>
    request<{ path: string; content: string }>(`/repos/${id}/file?path=${encodeURIComponent(path)}`),
  writeFile: (id: number, path: string, content: string, expected_content: string | null) =>
    request<{ path: string; saved: boolean }>(`/repos/${id}/file`, {
      method: "PUT",
      body: JSON.stringify({ path, content, expected_content }),
    }),
  search: (id: number, query: string) =>
    request<{ results: { path: string; line: number; text: string }[] }>(`/repos/${id}/search`, {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  gitStatus: (id: number) => request<{ branch: string; status: string }>(`/repos/${id}/git/status`),
  gitDiff: (id: number) => request<{ diff: string }>(`/repos/${id}/git/diff`),
  agentWorkspace: (id: number) => request<{ path: string; source: string }>(`/repos/${id}/agent-workspace`, { method: "POST" }),
  createTask: (title: string, description: string, workspace_id?: number) =>
    request<Task>("/tasks", {
      method: "POST",
      body: JSON.stringify({ title, description, workspace_id }),
    }),
  listTasks: () => request<Task[]>("/tasks"),
  getPlan: (taskId: number) => request<Plan>(`/tasks/${taskId}/plan`),
  generatePlan: (
    taskId: number,
    body: { workspace_path?: string; open_file_path?: string; selection?: string },
  ) => request<Plan>(`/tasks/${taskId}/plan/generate`, { method: "POST", body: JSON.stringify(body) }),
  approvePlan: (taskId: number) => request<Plan>(`/tasks/${taskId}/plan/approve`, { method: "POST" }),
  executeTask: (taskId: number, workspace_path: string) =>
    request<Task>(`/tasks/${taskId}/execute`, {
      method: "POST",
      body: JSON.stringify({ workspace_path }),
    }),
  cancelTask: (taskId: number) => request<Task>(`/tasks/${taskId}/cancel`, { method: "POST" }),
  retryTask: (taskId: number) => request<Task>(`/tasks/${taskId}/retry`, { method: "POST" }),
  events: (taskId: number) => request<TaskEvent[]>(`/tasks/${taskId}/events`),
};
