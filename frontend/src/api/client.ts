// 同源 /api 客户端：httpOnly Cookie 鉴权，统一错误处理。

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`;
    try {
      const data = await resp.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail[0]?.msg ?? detail;
    } catch {
      /* 非 JSON 响应 */
    }
    throw new ApiError(resp.status, detail);
  }
  const ct = resp.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) return resp.json();
  return resp.text() as unknown as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export function track(event: string, sessionId?: string, props: Record<string, unknown> = {}) {
  fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, session_id: sessionId ?? null, props }),
  }).catch(() => {});
}

// ---- 类型 ----
export interface User {
  id: string;
  email: string;
  display_name: string;
}

export interface DimProgress {
  key: string;
  short: string;
  questions_asked: number;
  evidence_state: string | null;
  done: boolean;
}

export interface Progress {
  dimensions: DimProgress[];
  total_questions: number;
  current_dimension: string | null;
}

export interface SessionBrief {
  id: string;
  mode: string;
  identity: string;
  status: string;
  turn_count: number;
  created_at: string;
  report_id: string | null;
  report_status: string | null;
}

export interface SessionDetail {
  id: string;
  mode: string;
  identity: string;
  status: string;
  messages: { seq: number; role: string; content: string }[];
  progress: Progress;
  report_id: string | null;
}

export interface ReportBrief {
  id: string;
  session_id: string;
  status: string;
  progress_stage: string | null;
  progress_text: string;
  version: number;
  error: string | null;
  can_retry: boolean;
  mode: string;
  identity: string;
  created_at: string;
}
