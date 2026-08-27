import type { AuthHeaders } from "../types";

export const visitorAuth: AuthHeaders = { role: "visitor", userId: "", token: "" };

// The role travelled in a header the browser wrote, so the server had only the
// caller's word for it. It now sends the token issued at login and the server
// looks the role up itself.
export const authHeaders = (auth: AuthHeaders) => ({
  "Content-Type": "application/json",
  ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {})
});

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function formatApiError(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (isRecord(detail)) {
    const message = String(detail.message || detail.detail || "요청 처리에 실패했습니다.");
    const hint = detail.hint ? ` ${String(detail.hint)}` : "";
    return `${message}${hint}`;
  }
  return String(detail);
}

export async function api<T>(
  path: string,
  auth: AuthHeaders,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...authHeaders(auth), ...(init?.headers || {}) }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && auth.token) {
      // An expired or revoked token would otherwise leave the console acting as
      // a visitor with no explanation, emptying the screen mid-task.
      const expired = new Error("세션이 만료되었습니다. 다시 로그인해주세요.");
      expired.name = "SessionExpired";
      throw expired;
    }
    throw new Error(formatApiError(data.detail) || `Request failed: ${response.status}`);
  }
  return data as T;
}

export async function publicApi<T>(path: string, force = false): Promise<T> {
  const response = await fetch(path, {
    cache: force ? "reload" : "default",
    headers: force ? { "Cache-Control": "no-cache" } : undefined
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatApiError(data.detail) || `Request failed: ${response.status}`);
  }
  return data as T;
}

export function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}
