import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  AgentScope,
  AuthHeaders,
  AuthSession,
  FrameworkPreset,
  IncompleteProject,
  Page,
  PanelMode,
  PendingDeploy,
  Project,
  Scope,
  SystemSummary
} from "./types";
import { api, errorText, publicApi, visitorAuth } from "./lib/api";
import { useMediaQuery } from "./lib/useMediaQuery";
import {
  clearStoredSession,
  loadPendingDeploy,
  loadRailWidth,
  loadStoredSession,
  storePendingDeploy,
  storeRailWidth,
  storeSession
} from "./lib/session";
import { AppHeader } from "./components/AppHeader";
import { ProjectIndex, PublicIndex } from "./components/ProjectIndex";
import { ProjectWorkspace } from "./components/ProjectWorkspace";
import { DeployForm } from "./components/DeployForm";
import { LoginModal } from "./components/LoginModal";
import { NewProjectModal } from "./components/NewProjectModal";
import { AgentPanel, RAIL_MIN, type AgentRequest } from "./components/agent/AgentPanel";
import { EmptyState, ErrorPanel } from "./components/States";
import "./styles.css";

/** Values typed on the deploy form, sent after the service exists. */
type DeployEnvEntry = { name: string; value: string; secret: boolean };

type ProjectsResponse = {
  projects: Project[];
  member_of?: string[];
  incomplete_projects?: IncompleteProject[];
};

function pageFromLocation(): Page {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const deploy = path.match(/^\/projects\/([^/]+)\/deploy$/);
  if (deploy) return { kind: "deploy", project: decodeURIComponent(deploy[1]) };
  const project = path.match(/^\/projects\/([^/]+)$/);
  if (project) return { kind: "project", project: decodeURIComponent(project[1]) };
  return { kind: "home" };
}

function pathForPage(page: Page) {
  if (page.kind === "project") return `/projects/${encodeURIComponent(page.project)}`;
  if (page.kind === "deploy") return `/projects/${encodeURIComponent(page.project)}/deploy`;
  return "/";
}

export function App() {
  const [session, setSession] = useState<AuthSession>(() => loadStoredSession());
  const [page, setPage] = useState<Page>(() => pageFromLocation());
  const [scope, setScope] = useState<Scope>("all");

  const [myProjects, setMyProjects] = useState<Project[]>([]);
  const [publicProjects, setPublicProjects] = useState<Project[]>([]);
  const [memberOf, setMemberOf] = useState<Set<string>>(new Set());
  const [incomplete, setIncomplete] = useState<IncompleteProject[]>([]);
  const [summary, setSummary] = useState<SystemSummary | null>(null);
  const [frameworks, setFrameworks] = useState<FrameworkPreset[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [publicError, setPublicError] = useState("");

  const [modal, setModal] = useState<"login" | "newProject" | null>(null);
  const [serverDetailOpen, setServerDetailOpen] = useState(false);
  const [justCreated, setJustCreated] = useState<string | null>(null);

  const [agentScopeKind, setAgentScopeKind] = useState<"project" | "root">("project");
  const [panelMode, setPanelMode] = useState<PanelMode>("rail");
  const [panelOpen, setPanelOpen] = useState(true);
  const [railWidth, setRailWidth] = useState(() => loadRailWidth(RAIL_MIN));
  const [agentRequest, setAgentRequest] = useState<AgentRequest | null>(null);
  const [mutationCount, setMutationCount] = useState(0);
  // A source build on this host runs for tens of minutes. The request is owned
  // here rather than by the form, so leaving the deploy screen -- or reloading
  // -- does not throw away the only record that it is running.
  const [pendingDeploy, setPendingDeploy] = useState<PendingDeploy | null>(() =>
    loadPendingDeploy()
  );

  // Below this the rail has no room; the panel becomes a bottom button that
  // opens fullscreen, per 2k.
  const narrow = useMediaQuery("(max-width: 1100px)");

  const auth = useMemo<AuthHeaders>(
    () => (session ? { role: session.role, userId: session.id, token: session.token } : visitorAuth),
    [session]
  );
  const role = auth.role;
  const isVisitor = role === "visitor";

  // --------------------------------------------------------------- routing
  function navigate(next: Page, replace = false) {
    const path = pathForPage(next);
    if (window.location.pathname !== path) {
      if (replace) window.history.replaceState(null, "", path);
      else window.history.pushState(null, "", path);
    }
    setPage(next);
  }

  useEffect(() => {
    const onPopState = () => setPage(pageFromLocation());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // ----------------------------------------------------------------- data
  const refreshProjects = useCallback(async () => {
    if (isVisitor) {
      setMyProjects([]);
      setMemberOf(new Set());
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api<ProjectsResponse>("/api/projects", auth);
      setMyProjects(data.projects || []);
      setMemberOf(new Set(data.member_of || (data.projects || []).map((item) => item.name)));
      setIncomplete(data.incomplete_projects || []);
    } catch (err) {
      if (err instanceof Error && err.name === "SessionExpired") {
        clearStoredSession();
        setSession(null);
      }
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [auth, isVisitor]);

  const refreshCatalog = useCallback(async () => {
    setPublicError("");
    try {
      const data = await publicApi<{ projects?: Project[] }>("/api/catalog");
      setPublicProjects(data.projects || []);
    } catch (err) {
      setPublicProjects([]);
      setPublicError(errorText(err));
    }
  }, []);

  const refreshSummary = useCallback(async () => {
    try {
      if (isVisitor) {
        const data = await publicApi<{ result?: SystemSummary }>("/api/system/public");
        setSummary(data.result || null);
        return;
      }
      const data = await api<{ result?: SystemSummary }>("/api/system/summary", auth);
      setSummary(data.result || null);
    } catch {
      setSummary(null);
    }
  }, [auth, isVisitor]);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshProjects(), refreshCatalog(), refreshSummary()]);
  }, [refreshProjects, refreshCatalog, refreshSummary]);

  /** A change the agent executed invalidates the summaries and the live rows. */
  const handleMutationDone = useCallback(() => {
    setMutationCount((count) => count + 1);
    void refreshAll();
  }, [refreshAll]);

  function clearPending(refresh: boolean) {
    setPendingDeploy(null);
    storePendingDeploy(null);
    if (refresh) void refreshAll();
  }

  /**
   * Hands the deploy to the server and returns immediately. The workspace shows
   * a row for it; this promise only exists to record the outcome, so nothing
   * here navigates or depends on the user still being on any given screen.
   */
  function startDeploy(
    targetProject: string,
    args: Record<string, unknown>,
    envEntries: DeployEnvEntry[]
  ) {
    const service = String(args.service || "");
    const pending: PendingDeploy = {
      project: targetProject,
      service,
      startedAt: Date.now(),
      state: "running"
    };
    setPendingDeploy(pending);
    storePendingDeploy(pending);
    navigate({ kind: "project", project: targetProject });

    void (async () => {
      try {
        await api(`/api/projects/${targetProject}/execute`, auth, {
          method: "POST",
          body: JSON.stringify({ skill: "service.deploy", arguments: args, approved: true })
        });
        // Values go in a second call: service.deploy is on the planner's tool
        // list, so its arguments must stay free of secrets. The service has to
        // exist first, and the container is recreated so the first run sees them.
        if (envEntries.length) {
          await api(`/api/projects/${targetProject}/execute`, auth, {
            method: "POST",
            body: JSON.stringify({
              skill: "service.env.set",
              arguments: { service, entries: envEntries, restart: true },
              approved: true
            })
          });
        }
        setPendingDeploy(null);
        storePendingDeploy(null);
        await refreshAll();
      } catch (err) {
        // The row keeps the reason on screen. A failed deploy rolls the compose
        // file back, so without this the service simply vanishes with no cause.
        const failed: PendingDeploy = { ...pending, state: "failed", error: errorText(err) };
        setPendingDeploy(failed);
        storePendingDeploy(failed);
      }
    })();
  }

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    void publicApi<{ frameworks?: FrameworkPreset[] }>("/api/frameworks")
      .then((data) => setFrameworks(data.frameworks || []))
      .catch(() => setFrameworks([]));
  }, []);

  useEffect(() => {
    if (isVisitor && page.kind !== "home") navigate({ kind: "home" }, true);
  }, [isVisitor, page.kind]);

  // ------------------------------------------------------------- projects
  const allProjects = useMemo(() => {
    if (role === "admin") return myProjects;
    // A member's own rows carry runtime detail the public catalog omits, so the
    // richer copy wins wherever both describe the same project. If the catalog
    // request failed, the user's own projects still have to be listed.
    const mine = new Map(myProjects.map((item) => [item.name, item]));
    const merged = publicProjects.map((item) => mine.get(item.name) ?? item);
    const seen = new Set(merged.map((item) => item.name));
    return [...merged, ...myProjects.filter((item) => !seen.has(item.name))];
  }, [role, myProjects, publicProjects]);

  const currentProject = useMemo(() => {
    if (page.kind === "home") return undefined;
    return (
      myProjects.find((item) => item.name === page.project) ??
      allProjects.find((item) => item.name === page.project) ?? { name: page.project }
    );
  }, [page, myProjects, allProjects]);

  const canOpenCurrent =
    page.kind === "home" || role === "admin" || memberOf.has(page.project);

  // ---------------------------------------------------------------- agent
  const agentScope: AgentScope =
    page.kind === "home"
      ? { kind: "root" }
      : agentScopeKind === "root" && role === "admin"
        ? { kind: "root" }
        : { kind: "project", name: page.project };

  function askAgent(text: string) {
    setPanelOpen(true);
    setAgentRequest({ nonce: Date.now(), kind: "prompt", text });
  }

  function requestApproval(skill: string, args: Record<string, unknown>) {
    setPanelOpen(true);
    setPanelMode((mode) => (mode === "full" ? mode : "rail"));
    setAgentRequest({ nonce: Date.now(), kind: "plan", skill, arguments: args });
  }

  const railStyle = { "--rail-w": `${railWidth}px` } as React.CSSProperties;

  // -------------------------------------------------------------- render
  let body: React.ReactNode;

  if (isVisitor) {
    body = (
      <PublicIndex
        projects={publicProjects}
        summary={summary}
        loading={loading}
        error={publicError}
        onRetry={() => void refreshCatalog()}
      />
    );
  } else if (page.kind === "home") {
    body = (
      <ProjectIndex
        role={role}
        scope={scope}
        onScopeChange={setScope}
        allProjects={allProjects}
        incomplete={incomplete}
        memberOf={memberOf}
        summary={summary}
        loading={loading}
        serverDetailOpen={serverDetailOpen}
        onToggleServerDetail={() => setServerDetailOpen(!serverDetailOpen)}
        onOpenProject={(project) => navigate({ kind: "project", project })}
        onNewProject={() => setModal("newProject")}
        agentSlot={
          role === "admin" ? (
            <div className="agentLauncher">
              <span className="agentMark" aria-hidden="true">
                AI
              </span>
              <span className="agentLauncher__title">운영 AI</span>
              <div className="segmented" role="group" aria-label="AI 범위">
                <button
                  className={agentScopeKind === "project" ? "is-active" : ""}
                  onClick={() => setAgentScopeKind("project")}
                >
                  프로젝트 선택
                </button>
                <button
                  className={agentScopeKind === "root" ? "is-active" : ""}
                  onClick={() => setAgentScopeKind("root")}
                >
                  전체 서버
                </button>
              </div>
              <button
                className="btn agentLauncher__open"
                onClick={() => {
                  if (agentScopeKind === "project") {
                    setModal(null);
                    return;
                  }
                  setPanelOpen(true);
                  setPanelMode("full");
                }}
                disabled={agentScopeKind === "project"}
              >
                열기
              </button>
            </div>
          ) : null
        }
      />
    );
  } else if (!canOpenCurrent) {
    body = (
      <div className="pageMain">
        <EmptyState
          title="이 프로젝트의 멤버가 아닙니다"
          body="참여 중인 프로젝트만 열 수 있습니다."
          action={
            <button className="btn" onClick={() => navigate({ kind: "home" })}>
              프로젝트 목록
            </button>
          }
        />
      </div>
    );
  } else if (page.kind === "deploy") {
    body = (
      <DeployForm
        auth={auth}
        project={page.project}
        projects={allProjects}
        summary={summary}
        frameworks={frameworks}
        onCancel={() => navigate({ kind: "project", project: page.project })}
        onStartDeploy={(args, envEntries) => startDeploy(page.project, args, envEntries)}
      />
    );
  } else {
    // One instance, both presentations. Switching to fullscreen must not throw
    // the conversation away, so the panel is never unmounted to change mode.
    const panel = panelOpen ? (
      <AgentPanel
        auth={auth}
        scope={agentScope}
        summary={summary}
        mode={panelMode}
        onModeChange={setPanelMode}
        railWidth={railWidth}
        onRailWidthChange={(width) => {
          setRailWidth(width);
          storeRailWidth(width);
        }}
        onClose={() => {
          setPanelOpen(false);
          setPanelMode("rail");
        }}
        request={agentRequest}
        onMutationDone={handleMutationDone}
        frameworks={frameworks}
      />
    ) : null;

    body = (
      <ProjectWorkspace
        auth={auth}
        project={currentProject!}
        summary={summary}
        justCreated={justCreated === page.project}
        onRefreshProjects={refreshAll}
        onDeploy={() => navigate({ kind: "deploy", project: page.project })}
        onRequestApproval={requestApproval}
        onAskAgent={askAgent}
        pendingDeploy={
          pendingDeploy && pendingDeploy.project === page.project ? pendingDeploy : null
        }
        onPendingDone={() => clearPending(true)}
        onPendingDismiss={() => clearPending(false)}
        refreshToken={mutationCount}
        railCollapsed={panelMode === "full" || narrow || !panelOpen}
        railSlot={panel}
        dock={
          narrow && panelMode !== "full" ? (
            <button
              className="btn btn--md btn--block"
              onClick={() => {
                setPanelOpen(true);
                setPanelMode("full");
              }}
            >
              운영 AI 열기
            </button>
          ) : null
        }
        headAction={
          !narrow && !panelOpen ? (
            <button className="btn btn--md" onClick={() => setPanelOpen(true)}>
              운영 AI
            </button>
          ) : null
        }
      />
    );
  }

  return (
    <div className="shell" style={railStyle}>
      <AppHeader
        page={page}
        session={session}
        onNavigate={(next) => navigate(next)}
        onLogin={() => setModal("login")}
        onLogout={() => {
          clearStoredSession();
          setSession(null);
          setMyProjects([]);
          setMemberOf(new Set());
          navigate({ kind: "home" });
        }}
      />

      {error && (
        <div className="pageMain" style={{ paddingBottom: 0 }}>
          <ErrorPanel
            title="프로젝트 목록을 불러오지 못했습니다"
            body={error}
            onRetry={() => void refreshProjects()}
            onDismiss={() => setError("")}
          />
        </div>
      )}

      <div className="shellBody">{body}</div>

      {/* Home has no rail to host the panel, so the root-scope conversation
          mounts here. Workspace pages render their own instance in the rail. */}
      {panelOpen && panelMode === "full" && !isVisitor && page.kind === "home" && (
        <AgentPanel
          auth={auth}
          scope={agentScope}
          summary={summary}
          mode="full"
          onModeChange={setPanelMode}
          railWidth={railWidth}
          onRailWidthChange={setRailWidth}
          onClose={() => {
            setPanelOpen(false);
            setPanelMode("rail");
          }}
          request={agentRequest}
          onMutationDone={handleMutationDone}
          frameworks={frameworks}
        />
      )}

      {modal === "login" && (
        <LoginModal
          onClose={() => setModal(null)}
          onSuccess={(next) => {
            storeSession(next);
            setSession(next);
            setModal(null);
          }}
        />
      )}

      {modal === "newProject" && (
        <NewProjectModal
          auth={auth}
          onClose={() => setModal(null)}
          onCreated={async (project, thenDeploy) => {
            setModal(null);
            setJustCreated(project);
            await refreshAll();
            navigate(thenDeploy ? { kind: "deploy", project } : { kind: "project", project });
          }}
        />
      )}
    </div>
  );
}
