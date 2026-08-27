import { ArrowUpRight } from "lucide-react";
import type { ProjectServiceSummary, ServiceAction, ServiceRuntime, ServiceState } from "../types";
import {
  DASH,
  barWidth,
  formatPorts,
  formatServiceMemory,
  publicUrl,
  serviceStateOf,
  statusBadge
} from "../lib/format";
import { ActionMenu, type MenuItem } from "./ActionMenu";

const RESTART_LOOP_AT = 5;

type RowActions = {
  primary: ServiceAction;
  primaryTone: "primary" | "quiet" | "secondary";
  secondary: ServiceAction | null;
  menu: ServiceAction[];
};

/**
 * The state decides which actions exist. Nothing is rendered and then blocked —
 * a running service simply has no `시작` button to press.
 */
export function actionsFor(state: ServiceState, restartCount: number): RowActions {
  if (state === "exited") {
    return {
      primary: "start",
      primaryTone: "primary",
      secondary: "logs",
      menu: ["ports", "redeploy"]
    };
  }
  if (state === "restarting" || restartCount >= RESTART_LOOP_AT) {
    // Looking at the cause has to come before restarting into the same failure.
    return {
      primary: "logs",
      primaryTone: "primary",
      secondary: "stop",
      menu: ["ports", "restart", "redeploy"]
    };
  }
  if (state === "unknown") {
    return {
      primary: "logs",
      primaryTone: "quiet",
      secondary: null,
      menu: ["ports", "restart", "redeploy"]
    };
  }
  return {
    primary: "logs",
    primaryTone: "quiet",
    secondary: "restart",
    menu: ["ports", "stop", "redeploy"]
  };
}

const MENU_META: Record<string, MenuItem> = {
  ports: { id: "ports", label: "포트 변경", section: "설정", hint: "승인 필요" },
  restart: { id: "restart", label: "재시작", section: "중단·교체", hint: "가역" },
  stop: { id: "stop", label: "중지", section: "중단·교체", hint: "가역" },
  redeploy: {
    id: "redeploy",
    label: "재배포",
    section: "중단·교체",
    hint: "승인 필요",
    danger: true
  }
};

function primaryLabel(action: ServiceAction, tone: RowActions["primaryTone"]) {
  if (action === "logs") return tone === "primary" ? "로그 보기" : "로그";
  if (action === "start") return "시작";
  return action;
}

export function ServiceRow({
  service,
  runtime,
  summary,
  busyAction,
  menuOpen,
  onMenuOpenChange,
  onAction
}: {
  service: string;
  runtime?: ServiceRuntime;
  summary?: ProjectServiceSummary;
  busyAction: string;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  onAction: (action: ServiceAction) => void;
}) {
  const container = runtime?.container;
  const restartCount = container?.restart_count ?? 0;
  const state = serviceStateOf(runtime);
  const badge = statusBadge(state, restartCount);
  const actions = actionsFor(state, restartCount);
  const url = publicUrl(runtime);
  const ports = formatPorts(runtime, summary);
  const memory = formatServiceMemory(container?.memory);
  const framework = summary?.framework_label || summary?.framework;
  const attention = state !== "running" || restartCount >= RESTART_LOOP_AT;
  const busy = Boolean(busyAction);

  const toneClass =
    badge.tone === "ok"
      ? "badge badge--ok"
      : badge.tone === "warn"
        ? "badge badge--warn"
        : badge.tone === "danger"
          ? "badge badge--danger"
          : "badge";

  return (
    <div className={attention ? "serviceRow serviceRow--attention" : "serviceRow"}>
      <div style={{ minWidth: 0 }}>
        <div className="serviceRow__name">
          <strong className="truncate" title={service}>
            {service}
          </strong>
          {url && (
            <a
              className="serviceRow__link"
              href={url}
              target="_blank"
              rel="noreferrer"
              title={url}
            >
              바로가기
              <ArrowUpRight size={11} aria-hidden="true" />
            </a>
          )}
          {restartCount >= RESTART_LOOP_AT && (
            <span className="serviceRow__restarts">재시작 {restartCount}회</span>
          )}
        </div>
        <div className="serviceRow__sub truncate">{framework || "프레임워크 확인 전"}</div>
      </div>

      <div>
        <span className={toneClass}>
          <span className={`badgeGlyph badgeGlyph--${badge.glyph}`} aria-hidden="true" />
          {badge.label}
        </span>
      </div>

      {/* Two grid cells on desktop, one grouped line inside the mobile card. */}
      <div className="serviceRow__facts">
        <div className={ports ? "serviceRow__port" : "cellEmpty"}>{ports ?? DASH}</div>
        <div className="serviceRow__memory">
          {memory ? (
            <>
              <div className="meter meter--sm" style={{ width: 52 }}>
                <i style={{ width: `${barWidth(container?.memory?.percent)}%` }} />
              </div>
              <span className="serviceRow__memoryValue">{memory}</span>
            </>
          ) : (
            <span className="cellEmpty">{DASH}</span>
          )}
        </div>
      </div>

      <div className="serviceRow__actions">
        <button
          className={
            actions.primaryTone === "primary"
              ? "btn btn--primary"
              : actions.primaryTone === "quiet"
                ? "btn btn--quiet"
                : "btn"
          }
          onClick={() => onAction(actions.primary)}
          disabled={busy}
        >
          {busyAction === actions.primary ? "실행 중" : primaryLabel(actions.primary, actions.primaryTone)}
        </button>
        {actions.secondary && (
          <button className="btn" onClick={() => onAction(actions.secondary!)} disabled={busy}>
            {busyAction === actions.secondary
              ? "실행 중"
              : actions.secondary === "logs"
                ? "로그"
                : actions.secondary === "stop"
                  ? "중지"
                  : "재시작"}
          </button>
        )}
        <ActionMenu
          label={`${service} 추가 작업`}
          items={actions.menu.map((id) => MENU_META[id]).filter(Boolean)}
          open={menuOpen}
          onOpenChange={onMenuOpenChange}
          onSelect={(id) => onAction(id as ServiceAction)}
        />
      </div>
    </div>
  );
}
