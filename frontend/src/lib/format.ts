import type {
  Project,
  ProjectServiceSummary,
  RuntimeMemory,
  ServiceRuntime,
  ServiceState
} from "../types";

export const PORT_RANGE_START = 9000;
export const PORT_RANGE_END = 9100;

/** Nothing measured yet. Never a zero, never filler prose. */
export const DASH = "—";

export function formatMb(value?: number | null): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  if (value >= 1024) {
    const gb = value / 1024;
    return `${gb >= 10 ? gb.toFixed(0) : gb.toFixed(1)}GB`;
  }
  return `${value % 1 ? value.toFixed(1) : value.toFixed(0)}MB`;
}

export function formatPercent(value?: number | null, digits = 1): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return `${value % 1 ? value.toFixed(digits) : value.toFixed(0)}%`;
}

export function clampPercent(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

/** A sliver of bar reads as "a little", an empty bar reads as broken. */
export function barWidth(percent?: number | null) {
  const value = clampPercent(percent);
  return value > 0 && value < 1 ? 1 : Math.round(value);
}

export function serviceSummaryName(service: ProjectServiceSummary) {
  return String(service.service || service.name || "");
}

export function projectServiceNames(project: Project) {
  const fromSummaries = (project.service_summaries || [])
    .map(serviceSummaryName)
    .filter(Boolean);
  return fromSummaries.length ? fromSummaries : project.services || [];
}

export function projectFrameworkLabels(project: Project) {
  const serviceLabels = (project.service_summaries || [])
    .map((service) => service.framework_label || service.framework)
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const labels = serviceLabels.length
    ? serviceLabels
    : (project.frameworks || []).map((item) => String(item || "").trim()).filter(Boolean);
  const seen = new Set<string>();
  return labels.filter((label) => {
    const key = label.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function urlForHostPort(hostPort?: number | string | null) {
  if (hostPort === undefined || hostPort === null || hostPort === "") return "";
  return `${window.location.protocol}//${window.location.hostname}:${hostPort}`;
}

export function projectPublicLinks(project: Project) {
  const links = (project.public_urls || [])
    .map((item) => ({
      service: String(item.service || ""),
      url: urlForHostPort(item.host_port)
    }))
    .filter((item) => item.url);
  if (links.length) return links;
  return (project.service_summaries || [])
    .filter((service) => service.frontend && service.host_port)
    .map((service) => ({
      service: serviceSummaryName(service),
      url: urlForHostPort(service.host_port)
    }))
    .filter((item) => item.url);
}

export function serviceStateOf(runtime?: ServiceRuntime): ServiceState {
  const status = runtime?.container?.status;
  if (!status) return "unknown";
  if (status === "running") return "running";
  if (status === "restarting") return "restarting";
  if (status === "exited" || status === "dead" || status === "paused" || status === "created") {
    return "exited";
  }
  return "unknown";
}

export type BadgeShape = "dot" | "diamond" | "bar" | "ring";

/**
 * Docker's RestartCount is a lifetime total, not a rate. demo-a has restarted
 * 13 times and has also been up and healthy for two months — reading that count
 * as "restarting in a loop" put a red badge on a service that is fine. Only the
 * restarting status says a container is failing right now.
 */
export function statusBadge(
  state: ServiceState
): { label: string; tone: "ok" | "warn" | "danger" | "neutral"; glyph: BadgeShape } {
  if (state === "running") return { label: "실행 중", tone: "ok", glyph: "dot" };
  if (state === "restarting") return { label: "재시작 중", tone: "warn", glyph: "diamond" };
  if (state === "exited") return { label: "중지됨", tone: "danger", glyph: "bar" };
  return { label: "확인 전", tone: "neutral", glyph: "ring" };
}

export function firstHostPort(runtime?: ServiceRuntime) {
  return (
    (runtime?.container?.ports || []).find((port) => port.host)?.host ?? runtime?.host_port ?? null
  );
}

export function publicUrl(runtime?: ServiceRuntime) {
  if (!runtime?.frontend) return "";
  const hostPort = firstHostPort(runtime);
  if (!hostPort) return "";
  return urlForHostPort(hostPort);
}

/**
 * `9000→3000` when a host port is published, the container port alone when it
 * is not. No public URL is information in itself, so it is not papered over
 * with words like "internal only".
 */
export function formatPorts(
  runtime?: ServiceRuntime,
  summary?: ProjectServiceSummary
): string | null {
  const mapped = (runtime?.container?.ports || []).filter((port) => port.host && port.container);
  if (mapped.length) {
    return mapped.map((port) => `${port.host}→${String(port.container).split("/")[0]}`).join(", ");
  }
  const configured = (runtime?.configured_ports || []).map(String).filter(Boolean);
  if (configured.length) return configured.join(", ");
  const containerPort = summary?.container_port;
  if (containerPort) return String(containerPort);
  return null;
}

export function formatServiceMemory(memory?: RuntimeMemory | null): string | null {
  const usage = formatMb(memory?.usage_mb);
  if (!usage) return null;
  const percent = formatPercent(memory?.percent);
  return percent ? `${usage} · ${percent}` : usage;
}

export function formatRelativeDate(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const diffSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  const steps: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 60 * 60 * 24 * 365],
    ["month", 60 * 60 * 24 * 30],
    ["day", 60 * 60 * 24],
    ["hour", 60 * 60],
    ["minute", 60]
  ];
  const formatter = new Intl.RelativeTimeFormat("ko", { numeric: "auto" });
  for (const [unit, seconds] of steps) {
    if (Math.abs(diffSeconds) >= seconds) {
      return formatter.format(Math.round(diffSeconds / seconds), unit);
    }
  }
  return "방금 전";
}

/** Elapsed time for a running deploy, coarse on purpose. */
export function formatElapsed(startedAt: number, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - startedAt) / 1000));
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분`;
}

export function formatClock(date = new Date()) {
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/**
 * The lowest host port nothing is published on. Derived from what the projects
 * report rather than guessed, so the strip never advertises a taken port.
 */
export function availablePortRange(projects: Project[]) {
  const used = new Set<number>();
  for (const project of projects) {
    for (const link of project.public_urls || []) {
      const port = Number(link.host_port);
      if (Number.isFinite(port)) used.add(port);
    }
    for (const service of project.service_summaries || []) {
      const port = Number(service.host_port);
      if (Number.isFinite(port)) used.add(port);
    }
  }
  let start = PORT_RANGE_START;
  while (used.has(start) && start <= PORT_RANGE_END) start += 1;
  if (start > PORT_RANGE_END) return null;
  return `${start}–${PORT_RANGE_END}`;
}

export function nextFreePort(projects: Project[]) {
  const range = availablePortRange(projects);
  return range ? Number(range.split("–")[0]) : PORT_RANGE_START;
}

/** Why a project row is flagged, said in the row rather than as a count. */
export function projectAttention(
  project: Project,
  incompleteReason?: string
): { level: "danger" | "warn" | "none"; text: string; badge?: string } {
  if (incompleteReason) {
    return {
      level: "warn",
      text: "compose 파일 없음 — 서비스 배포로 복구 가능",
      badge: "미완성"
    };
  }
  if (project.runtime_error) {
    return { level: "danger", text: "상태를 확인하지 못했습니다", badge: "확인 실패" };
  }
  const attention = project.attention_count ?? 0;
  if (attention > 0) {
    const troubled = (project.service_summaries || []).filter(
      (service) => service.status && service.status !== "running"
    );
    const named = troubled
      .slice(0, 2)
      .map((service) => {
        const label = statusBadge(
          service.status === "restarting" ? "restarting" : "exited"
        ).label;
        return `${serviceSummaryName(service)} ${label}`;
      })
      .filter(Boolean);
    return {
      level: "danger",
      text: named.length ? named.join(" · ") : `확인이 필요한 서비스 ${attention}개`,
      badge: `주의 ${attention}`
    };
  }
  return { level: "none", text: "" };
}

export function skillLabel(skill?: string) {
  const labels: Record<string, string> = {
    "project.create": "프로젝트 생성",
    "project.list": "프로젝트 목록 조회",
    "server.health": "서버 상태 점검",
    "service.deploy": "새 서비스 배포",
    "service.redeploy": "기존 서비스 재배포",
    "service.logs": "서비스 로그 확인",
    "service.status": "서비스 상태 확인",
    "service.control": "서비스 상태 변경",
    "service.delete": "서비스 영구 삭제",
    "port.manage": "포트 변경",
    "repository.inspect": "저장소 확인",
    "framework.list": "프레임워크 목록",
    "qa.run": "인프라 점검"
  };
  return labels[skill || ""] || skill || "실행 작업";
}

/**
 * The verb alone, for places that already name the target: a card titled
 * "demo-b 재배포" reads better than "demo-b 기존 서비스 재배포".
 */
export function skillAction(skill: string, args: Record<string, unknown> = {}) {
  if (skill === "service.control") {
    return serviceActionLabel(String(args.action || "상태 변경"));
  }
  const actions: Record<string, string> = {
    "project.create": "생성",
    "service.deploy": "배포",
    "service.redeploy": "재배포",
    "service.delete": "삭제",
    "port.manage": "포트 변경"
  };
  return actions[skill] || skillLabel(skill);
}

/**
 * 을/를 depends on whether the last syllable has a final consonant, so the
 * particle cannot be baked into a sentence template.
 */
export function objectParticle(word: string) {
  const code = word.charCodeAt(word.length - 1);
  if (Number.isNaN(code) || code < 0xac00 || code > 0xd7a3) return "를";
  return (code - 0xac00) % 28 === 0 ? "를" : "을";
}

export function serviceActionLabel(action: string) {
  const labels: Record<string, string> = {
    logs: "로그",
    start: "시작",
    stop: "중지",
    restart: "재시작",
    redeploy: "재배포",
    ports: "포트 변경",
    delete: "삭제"
  };
  return labels[action] || action;
}
