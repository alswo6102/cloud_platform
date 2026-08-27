import type { AuthSession } from "../types";
import { isRecord } from "./api";

const SESSION_STORAGE_KEY = "cloud-platform-console-session";

export function loadStoredSession(): AuthSession {
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!isRecord(data) || typeof data.id !== "string") return null;
    if (data.role !== "user" && data.role !== "admin") return null;
    // Sessions saved before tokens existed carry no credential; treat them as
    // signed out so the user logs in again rather than silently acting as a
    // visitor on every request.
    if (typeof data.token !== "string" || !data.token) return null;
    return {
      id: data.id,
      role: data.role,
      name: typeof data.name === "string" ? data.name : undefined,
      token: data.token
    };
  } catch {
    return null;
  }
}

export function storeSession(session: NonNullable<AuthSession>) {
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    /* private mode: the session simply does not survive a reload */
  }
}

export function clearStoredSession() {
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    /* nothing to clear */
  }
}

const RAIL_WIDTH_KEY = "cloud-platform-console-rail-width";

export function loadRailWidth(fallback: number) {
  try {
    const raw = window.localStorage.getItem(RAIL_WIDTH_KEY);
    const value = Number(raw);
    return Number.isFinite(value) && value > 0 ? value : fallback;
  } catch {
    return fallback;
  }
}

export function storeRailWidth(width: number) {
  try {
    window.localStorage.setItem(RAIL_WIDTH_KEY, String(Math.round(width)));
  } catch {
    /* width just does not persist */
  }
}
