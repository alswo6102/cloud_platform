import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AuthHeaders,
  Project,
  ServiceAction,
  ServiceRuntime,
  SystemSummary
} from "../types";
import { api, errorText, isRecord } from "../lib/api";
import {
  formatMb,
  formatPercent,
  formatRelativeDate,
  projectServiceNames,
  serviceActionLabel,
  serviceStateOf
} from "../lib/format";
import { ServiceRow } from "./ServiceRow";
import { EmptyState, ErrorPanel, InlineConfirm, TableSkeleton, useDelayedFlag } from "./States";
import "./ProjectWorkspace.css";

type LogOutput = { service: string; text: string };

/** Reversible enough to confirm in place; nothing here needs the AI panel. */
const INLINE_CONFIRM: ServiceAction[] = ["stop"];
/** Replaces a running container — always the approval card. */
const NEEDS_APPROVAL: ServiceAction[] = ["redeploy"];

export function ProjectWorkspace({
  auth,
  project,
  summary,
  justCreated,
  onRefreshProjects,
  onDeploy,
  onRequestApproval,
  onAskAgent,
  refreshToken,
  railSlot,
  railCollapsed,
  dock,
  headAction
}: {
  auth: AuthHeaders;
  project: Project;
  summary: SystemSummary | null;
  justCreated: boolean;
  onRefreshProjects: () => Promise<void>;
  onDeploy: () => void;
  onRequestApproval: (skill: string, args: Record<string, unknown>) => void;
  onAskAgent: (text: string) => void;
  /** Bumped when the agent panel executes a change, to re-read service state. */
  refreshToken: number;
  railSlot?: React.ReactNode;
  railCollapsed?: boolean;
  dock?: React.ReactNode;
  headAction?: React.ReactNode;
}) {
  const [runtime, setRuntime] = useState<Record<string, ServiceRuntime>>({});
  const [loading, setLoading] = useState(true);
  const [runtimeError, setRuntimeError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [log, setLog] = useState<LogOutput | null>(null);
  const [openMenuFor, setOpenMenuFor] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<{ service: string; action: ServiceAction } | null>(
    null
  );
  const showSkeleton = useDelayedFlag(loading);
  const projectName = project.name;
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refreshRuntime = useCallback(
    async (force = false) => {
      setLoading(true);
      setRuntimeError("");
      try {
        const data = await api<{ result?: { services?: ServiceRuntime[] } }>(
          `/api/projects/${projectName}/execute`,
          auth,
          {
            method: "POST",
            headers: force ? { "Cache-Control": "no-cache" } : undefined,
            body: JSON.stringify({ skill: "service.status", arguments: {}, approved: true })
          }
        );
        if (!mounted.current) return;
        const next: Record<string, ServiceRuntime> = {};
        for (const item of data.result?.services || []) next[item.service] = item;
        setRuntime(next);
      } catch (err) {
        if (mounted.current) setRuntimeError(errorText(err));
      } finally {
        if (mounted.current) setLoading(false);
      }
    },
    [auth, projectName]
  );

  useEffect(() => {
    void refreshRuntime();
  }, [refreshRuntime]);

  // An approved port change rewrites the compose mapping; without this the
  // table kept showing the port the service no longer listens on.
  useEffect(() => {
    if (refreshToken > 0) void refreshRuntime(true);
  }, [refreshToken, refreshRuntime]);

  async function run(service: string, action: ServiceAction) {
    setBusyAction(`${service}:${action}`);
    setLog(null);
    try {
      const body =
        action === "logs"
          ? { skill: "service.logs", arguments: { service, lines: 80 }, approved: true }
          : { skill: "service.control", arguments: { service, action }, approved: true };
      const data = await api<Record<string, unknown>>(
        `/api/projects/${projectName}/execute`,
        auth,
        { method: "POST", body: JSON.stringify(body) }
      );
      if (action === "logs") {
        const result = isRecord(data.result) ? data.result : {};
        setLog({ service, text: String(result.logs || "로그가 비어 있습니다.") });
      } else {
        await Promise.all([onRefreshProjects(), refreshRuntime(true)]);
      }
    } catch (err) {
      setRuntimeError(errorText(err));
    } finally {
      setBusyAction("");
    }
  }

  function handleAction(service: string, action: ServiceAction) {
    // A port change needs a number the row cannot supply. Hand it to the
    // conversation, which already knows how to ask for one missing field and
    // comes back with a real plan; a redeploy needs nothing but the service.
    if (action === "ports") {
      onAskAgent(`${service} 서비스의 호스트 포트를 바꾸고 싶어`);
      return;
    }
    if (NEEDS_APPROVAL.includes(action)) {
      onRequestApproval("service.redeploy", { project: projectName, service });
      return;
    }
    if (INLINE_CONFIRM.includes(action)) {
      setConfirming({ service, action });
      return;
    }
    void run(service, action);
  }

  const services = projectServiceNames(project);
  const summaries = new Map(
    (project.service_summaries || []).map((item) => [String(item.service || item.name), item])
  );
  const runtimeList = Object.values(runtime);
  const running = runtimeList.length
    ? runtimeList.filter((item) => serviceStateOf(item) === "running").length
    : (project.running_count ?? 0);
  const total = runtimeList.length || project.service_count || services.length;
  const memoryUsed = runtimeList.length
    ? runtimeList.reduce((sum, item) => sum + (item.container?.memory?.usage_mb ?? 0), 0)
    : project.memory_total_mb;
  const memoryText = formatMb(memoryUsed);
  const memoryTotalText = formatMb(summary?.memory_total_mb);
  const memoryShare =
    memoryUsed && summary?.memory_total_mb
      ? formatPercent((memoryUsed / summary.memory_total_mb) * 100)
      : null;
  const lastDeployed = formatRelativeDate(project.last_deployed_at);
  const allRunning = total > 0 && running === total;

  return (
    <div className={railCollapsed ? "workspace workspace--noRail" : "workspace"}>
      <main className="workspace__main">
        <div className="workspaceHead">
          <div className="workspaceHead__ident">
            <h1 className="workspaceHead__title truncate" title={projectName}>
              {projectName}
            </h1>
            <div className="workspaceMeta">
              {justCreated ? (
                <span>방금 만들어짐</span>
              ) : (
                <>
                  <span
                    className={
                      allRunning
                        ? "workspaceMeta__dot"
                        : total === 0
                          ? "workspaceMeta__dot workspaceMeta__dot--idle"
                          : "workspaceMeta__dot workspaceMeta__dot--warn"
                    }
                  >
                    <i aria-hidden="true" />
                    {total === 0
                      ? "서비스 없음"
                      : allRunning
                        ? `서비스 ${total}개 모두 실행 중`
                        : `서비스 ${running}/${total} 실행 중`}
                  </span>
                  {memoryText && (
                    <>
                      <span className="workspaceMeta__sep">·</span>
                      <span>
                        메모리 <b className="num">{memoryText}</b>
                        {memoryTotalText && ` / ${memoryTotalText}`}
                        {memoryShare && <span className="workspaceMeta__soft"> ({memoryShare})</span>}
                      </span>
                    </>
                  )}
                  <span className="workspaceMeta__sep">·</span>
                  <span>
                    마지막 배포 <b>{lastDeployed || "기록 없음"}</b>
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="workspaceHead__actions">
            {headAction}
            <button className="btn btn--primary btn--md" onClick={onDeploy}>
              새 서비스 배포
            </button>
          </div>
        </div>

        {runtimeError && (
          <div className="workspaceAlert">
            <ErrorPanel
              title="서비스 상태를 불러오지 못했습니다"
              body={runtimeError}
              onRetry={() => void refreshRuntime(true)}
              onDismiss={() => setRuntimeError("")}
            />
          </div>
        )}

        {confirming && (
          <div className="workspaceAlert">
            <InlineConfirm
              title={`${confirming.service}을(를) 중지할까요?`}
              body="컨테이너가 멈추고, 공개 URL이 있으면 즉시 끊깁니다. 다시 시작할 수 있습니다."
              confirmLabel={serviceActionLabel(confirming.action)}
              onConfirm={() => {
                const target = confirming;
                setConfirming(null);
                void run(target.service, target.action);
              }}
              onCancel={() => setConfirming(null)}
            />
          </div>
        )}

        <div className="serviceTable">
          <div className="serviceTable__head" role="presentation">
            <div>서비스</div>
            <div>상태</div>
            <div>포트</div>
            <div>메모리</div>
            <div />
          </div>

          {services.length === 0 ? (
            <EmptyState
              title="아직 서비스가 없습니다"
              body="GitHub 저장소 하나로 첫 서비스를 올릴 수 있습니다."
              action={
                <button className="btn btn--primary btn--md" onClick={onDeploy}>
                  새 서비스 배포
                </button>
              }
            />
          ) : showSkeleton && runtimeList.length === 0 ? (
            <TableSkeleton
              rows={services.length}
              note="Docker stats를 읽는 중입니다 · 3초 넘으면 캐시된 값을 먼저 보여줍니다"
            />
          ) : (
            services.map((service) => (
              <ServiceRow
                key={service}
                service={service}
                runtime={runtime[service]}
                summary={summaries.get(service)}
                busyAction={
                  busyAction.startsWith(`${service}:`) ? busyAction.split(":")[1] || "" : ""
                }
                menuOpen={openMenuFor === service}
                onMenuOpenChange={(open) => setOpenMenuFor(open ? service : null)}
                onAction={(action) => handleAction(service, action)}
              />
            ))
          )}
        </div>

        {log && (
          <div className="logPanel">
            <div className="logPanel__head">
              <span className="logPanel__title">{log.service}</span>
              <span className="logPanel__meta">최근 80줄</span>
              <button className="btn btn--quiet logPanel__close" onClick={() => setLog(null)}>
                닫기
              </button>
            </div>
            <pre className="logPanel__body">{log.text}</pre>
          </div>
        )}

        {services.length > 0 && (
          <p className="tableNote">
            재시작이 반복되는 서비스는 주 동작이 <b>로그 보기</b>로 바뀝니다. 원인을 보기 전에
            재시작을 다시 누르게 하지 않습니다.
          </p>
        )}
      </main>

      {railSlot}
      {dock && <div className="agentDock">{dock}</div>}
    </div>
  );
}
