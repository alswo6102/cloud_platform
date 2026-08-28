import type { AuthSession, PendingDeploy } from "../types";
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

const PENDING_DEPLOY_KEY = "cloud-platform-console-pending-deploy";
/** Past this a stored deploy is stale rather than slow, and is dropped. */
const PENDING_DEPLOY_MAX_AGE_MS = 3 * 60 * 60 * 1000;

/**
 * A build here runs for tens of minutes, so a reload in the middle is normal.
 * Without this the row would come back as "확인 전" and be indistinguishable
 * from a service whose container had died.
 */
export function loadPendingDeploy(): PendingDeploy | null {
  try {
    const raw = window.localStorage.getItem(PENDING_DEPLOY_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!isRecord(data)) return null;
    if (typeof data.project !== "string" || typeof data.service !== "string") return null;
    if (typeof data.startedAt !== "number") return null;
    if (data.state !== "running" && data.state !== "failed") return null;
    if (Date.now() - data.startedAt > PENDING_DEPLOY_MAX_AGE_MS) return null;
    return {
      project: data.project,
      service: data.service,
      startedAt: data.startedAt,
      state: data.state,
      error: typeof data.error === "string" ? data.error : undefined
    };
  } catch {
    return null;
  }
}

export function storePendingDeploy(pending: PendingDeploy | null) {
  try {
    if (!pending) window.localStorage.removeItem(PENDING_DEPLOY_KEY);
    else window.localStorage.setItem(PENDING_DEPLOY_KEY, JSON.stringify(pending));
  } catch {
    /* private mode: the row just does not survive a reload */
  }
}
