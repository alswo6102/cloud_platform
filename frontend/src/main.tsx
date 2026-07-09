import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Role = "visitor" | "user" | "admin";
type Page = { kind: "home" } | { kind: "project"; project: string };
type QuickPrompt = { id: number; text: string };
type FrameworkId =
  | "static"
  | "vite"
  | "react"
  | "nextjs"
  | "express"
  | "fastapi"
  | "flask"
  | "django"
  | "spring-maven"
  | "go"
  | "existing";

type Project = {
  name: string;
  services?: string[];
};

type PublicCatalog = {
  projects?: Project[];
};

type RuntimePort = {
  host?: number | string;
  container?: number | string;
};

type RuntimeMemory = {
  usage_mb?: number;
  limit_mb?: number | null;
  percent?: number | null;
};

type RuntimeContainer = {
  name?: string;
  status?: string;
  health?: string | null;
  restart_count?: number;
  ports?: RuntimePort[];
  memory?: RuntimeMemory | null;
};

type ServiceRuntime = {
  service: string;
  configured_ports?: string[];
  frontend?: boolean;
  container?: RuntimeContainer | null;
};

type SystemSummary = {
  docker?: boolean;
  containers?: number;
  running?: number;
  disk_percent?: number;
  memory_percent?: number;
  unhealthy?: string[];
  restarting?: string[];
};

type ServiceActionOutput = {
  title: string;
  text: string;
  tone?: "ok" | "warn" | "error";
};

type AuthSession = {
  id: string;
  role: Role;
  name?: string;
} | null;

type AuthHeaders = {
  role: Role;
  userId: string;
};

type ChatMessage = {
  from: "user" | "agent";
  text: string;
  approval?: ApprovalRequest;
};

type ApprovalRequest = {
  skill: string;
  arguments: Record<string, unknown>;
  preview?: unknown;
  resume?: unknown;
  status: "pending" | "executing" | "done" | "failed";
};

type AgentResponse = {
  message?: string;
  context?: Record<string, unknown>;
  requires_approval?: boolean;
  skill?: string;
  arguments?: Record<string, unknown>;
  preview?: unknown;
  resume?: unknown;
  ui?: UiHint | null;
  field_errors?: Record<string, string>;
  error?: unknown;
};

type ApprovalAgentResponse = AgentResponse & {
  requires_approval: true;
  skill: string;
  arguments: Record<string, unknown>;
};

type UiHint = {
  type?: string;
  form?: string;
  arguments?: Record<string, unknown>;
  missing?: Array<Record<string, unknown>>;
  field_errors?: Record<string, string>;
};

type DeployGuideState = {
  service: string;
  repoUrl: string;
  framework: FrameworkId | "";
  isWeb: "web" | "internal";
  useDefaults: boolean;
  hostPort: string;
  envNames: string;
};

const frameworkOptions: Array<{
  id: FrameworkId;
  label: string;
  hint: string;
}> = [
  { id: "static", label: "Vanilla JS / Static", hint: "HTML/CSS/JS를 빌드 없이 서빙" },
  { id: "vite", label: "Vite", hint: "React/Vue/Svelte Vite 앱" },
  { id: "react", label: "Create React App", hint: "CRA 기반 프론트엔드" },
  { id: "nextjs", label: "Next.js", hint: "Next.js 앱" },
  { id: "express", label: "Express / Node", hint: "Node.js 웹 서버" },
  { id: "fastapi", label: "FastAPI", hint: "Python FastAPI 백엔드" },
  { id: "flask", label: "Flask", hint: "Python Flask 백엔드" },
  { id: "django", label: "Django", hint: "Python Django 백엔드" },
  { id: "spring-maven", label: "Spring Maven", hint: "Java Spring Boot Maven" },
  { id: "go", label: "Go", hint: "Go 웹 서비스" },
  { id: "existing", label: "기존 Dockerfile", hint: "저장소의 Dockerfile 그대로 사용" }
];

const visitorAuth: AuthHeaders = {
  role: "visitor",
  userId: ""
};

const SESSION_STORAGE_KEY = "cloud-platform-console-session";

const authHeaders = (auth: AuthHeaders) => ({
  "Content-Type": "application/json",
  "X-User-Role": auth.role,
  "X-User-Id": auth.userId
});

async function api<T>(path: string, auth: AuthHeaders, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...authHeaders(auth),
      ...(init?.headers || {})
    }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatApiError(data.detail) || `Request failed: ${response.status}`);
  }
  return data as T;
}

function formatApiError(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (isRecord(detail)) {
    const message = String(detail.message || detail.detail || "요청 처리에 실패했습니다.");
    const hint = detail.hint ? ` ${String(detail.hint)}` : "";
    return `${message}${hint}`;
  }
  return String(detail);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isApprovalAgentResponse(data: AgentResponse): data is ApprovalAgentResponse {
  return data.requires_approval === true && typeof data.skill === "string" && isRecord(data.arguments);
}

function normalizeFramework(value: unknown): FrameworkId | "" {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return "";
  const aliases: Record<string, FrameworkId> = {
    static: "static",
    "vanilla js": "static",
    javascript: "static",
    vite: "vite",
    react: "react",
    next: "nextjs",
    nextjs: "nextjs",
    "next.js": "nextjs",
    express: "express",
    nestjs: "express",
    fastapi: "fastapi",
    flask: "flask",
    django: "django",
    spring: "spring-maven",
    "spring-maven": "spring-maven",
    go: "go",
    golang: "go",
    existing: "existing",
    dockerfile: "existing"
  };
  return aliases[raw] || "";
}

function isDeployFormHint(data: AgentResponse) {
  return data.ui?.type === "form" && data.ui.form === "service.deploy";
}

function loadStoredSession(): AuthSession {
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!isRecord(data) || typeof data.id !== "string") return null;
    if (data.role !== "user" && data.role !== "admin") return null;
    return {
      id: data.id,
      role: data.role,
      name: typeof data.name === "string" ? data.name : undefined
    };
  } catch {
    return null;
  }
}

function storeSession(session: NonNullable<AuthSession>) {
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

function clearStoredSession() {
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

function newSessionId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const randomPart = Math.random().toString(36).slice(2);
  return `session-${Date.now().toString(36)}-${randomPart}`;
}

function labelSkill(skill?: string) {
  const labels: Record<string, string> = {
    "project.create": "프로젝트 생성",
    "service.deploy": "새 서비스 배포",
    "service.redeploy": "기존 서비스 재배포",
    "service.control": "서비스 제어",
    "port.manage": "포트 변경"
  };
  return labels[skill || ""] || skill || "실행 작업";
}

function summarizeApproval(data: AgentResponse) {
  const args = data.arguments || {};
  const preview = isRecord(data.preview) ? data.preview : {};
  const project = String(args.project || preview.project || "현재 프로젝트");
  const service = args.service ? ` / 서비스: ${String(args.service)}` : "";
  return [
    `${labelSkill(data.skill)} 실행 전 확인이 필요합니다.`,
    `대상: ${project}${service}`,
    "필요한 정보가 확인됐습니다. 아래 내용을 검토한 뒤 승인하면 작업을 시작합니다."
  ].join("\n");
}

function summarizeExecution(data: unknown) {
  if (!isRecord(data)) return "작업을 실행했습니다.";
  const result = isRecord(data.result) ? data.result : data;
  const status = result.status || result.message || result.action;
  if (status) return `작업을 실행했습니다.\n결과: ${String(status)}`;
  return "작업을 실행했습니다. 화면을 새로고침해 최신 상태를 확인해주세요.";
}

function previewSteps(preview: unknown): string[] {
  if (!isRecord(preview) || !Array.isArray(preview.steps)) return [];
  const labels: Record<string, string> = {
    "clone the latest default branch into a temporary directory": "최신 코드를 임시 공간에 내려받습니다.",
    "validate the new root-level Dockerfile": "배포에 필요한 Dockerfile을 확인합니다.",
    "atomically swap the service source directory": "기존 서비스 소스와 새 소스를 안전하게 교체합니다.",
    "build a new image and force-recreate only the target service": "대상 서비스만 새 이미지로 다시 빌드합니다.",
    "verify the new container stays running": "새 컨테이너가 정상 실행되는지 확인합니다.",
    "restore the previous source and container if verification fails": "검증 실패 시 이전 상태로 복구합니다."
  };
  return preview.steps
    .filter((item): item is string => typeof item === "string")
    .map((item) => labels[item] || item);
}

function cleanInlineMarkdown(text: string) {
  return text
    .replace(/\*\*/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function MessageText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="messageText">
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) return <div className="messageGap" key={index} />;
        if (trimmed.startsWith("###")) {
          return <strong className="messageHeading" key={index}>{cleanInlineMarkdown(trimmed.replace(/^#+\s*/, ""))}</strong>;
        }
        if (trimmed.startsWith("- ")) {
          return <div className="messageListItem" key={index}>• {cleanInlineMarkdown(trimmed.slice(2))}</div>;
        }
        return <p key={index}>{cleanInlineMarkdown(trimmed)}</p>;
      })}
    </div>
  );
}

function pageFromLocation(): Page {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const match = path.match(/^\/projects\/([^/]+)$/);
  if (match) return { kind: "project", project: decodeURIComponent(match[1]) };
  return { kind: "home" };
}

function pathForPage(page: Page) {
  if (page.kind === "project") return `/projects/${encodeURIComponent(page.project)}`;
  return "/";
}

function makeQuickPrompt(text: string): QuickPrompt {
  return { id: Date.now(), text };
}

function App() {
  const [session, setSession] = useState<AuthSession>(() => loadStoredSession());
  const [projects, setProjects] = useState<Project[]>([]);
  const [publicProjects, setPublicProjects] = useState<Project[]>([]);
  const [systemSummary, setSystemSummary] = useState<SystemSummary | null>(null);
  const [page, setPage] = useState<Page>(() => pageFromLocation());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(() => Boolean(loadStoredSession()));
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const auth = useMemo<AuthHeaders>(
    () => session ? { role: session.role, userId: session.id } : visitorAuth,
    [session]
  );
  const role = auth.role;
  const selectedProject = page.kind === "project"
    ? projects.find((project) => project.name === page.project)
    : undefined;
  const projectNames = useMemo(() => new Set(projects.map((project) => project.name)), [projects]);

  async function refreshPublicProjects() {
    try {
      const data = await api<PublicCatalog>("/api/catalog", visitorAuth);
      setPublicProjects(data.projects || []);
    } catch {
      setPublicProjects([]);
    }
  }

  async function refreshProjects() {
    if (role === "visitor") {
      setProjects([]);
      setProjectsLoaded(true);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api<{ projects: Project[] }>("/api/projects", auth);
      setProjects(data.projects || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProjectsLoaded(true);
      setLoading(false);
    }
  }

  async function refreshSystemSummary() {
    if (role === "visitor") {
      setSystemSummary(null);
      return;
    }
    try {
      const data = await api<{ result?: SystemSummary }>("/api/system/summary", auth);
      setSystemSummary(data.result || null);
    } catch {
      setSystemSummary(null);
    }
  }

  async function refreshAll() {
    await Promise.all([refreshPublicProjects(), refreshProjects(), refreshSystemSummary()]);
  }

  useEffect(() => {
    refreshPublicProjects();
  }, []);

  useEffect(() => {
    const handlePopState = () => setPage(pageFromLocation());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    setProjectsLoaded(false);
    refreshProjects();
    refreshSystemSummary();
    if (role === "visitor" && page.kind === "project") {
      navigateHome(true);
    }
  }, [role, auth.userId]);

  function navigate(page: Page, replace = false) {
    const path = pathForPage(page);
    if (window.location.pathname !== path) {
      if (replace) {
        window.history.replaceState(null, "", path);
      } else {
        window.history.pushState(null, "", path);
      }
    }
    setPage(page);
  }

  function navigateHome(replace = false) {
    navigate({ kind: "home" }, replace);
  }

  function openProject(project: string) {
    if (role === "visitor") {
      setError("로그인 후 접근할 수 있습니다.");
      navigateHome();
      return;
    }
    if (!projectNames.has(project) && role !== "admin") {
      setError(`${project} 프로젝트에 대한 권한이 없습니다.`);
      navigateHome();
      return;
    }
    setError("");
    navigate({ kind: "project", project });
  }

  return (
    <main className="shell">
      <header className="appHeader">
        <div className="brandLockup">
          <span className="brandMark" aria-hidden="true">◇</span>
          <div>
            <strong>Cloud Platform</strong>
            <span>Deploy console</span>
          </div>
        </div>
        <LoginPanel
          session={session}
          onLogin={(next) => {
            storeSession(next);
            setSession(next);
            setError("");
          }}
          onLogout={() => {
            clearStoredSession();
            setSession(null);
            setProjects([]);
            setProjectsLoaded(false);
            navigateHome();
          }}
        />
      </header>

      {error && <div className="error">{error}</div>}

      {page.kind === "home" ? (
        <HomePage
          auth={auth}
          role={role}
          session={session}
          systemSummary={systemSummary}
          publicProjects={publicProjects}
          projects={projects}
          loading={loading}
          onOpenProject={openProject}
          onCreated={async (project) => {
            await refreshAll();
            navigate({ kind: "project", project });
          }}
        />
      ) : selectedProject ? (
        <ProjectWorkspace
          auth={auth}
          project={selectedProject}
          onBack={() => navigateHome()}
          onRefresh={refreshAll}
        />
      ) : (
        <section className="workspace">
          <button className="secondaryButton" onClick={() => navigateHome()}>메인으로</button>
          <p className="hint">
            {role !== "visitor" && (!projectsLoaded || loading || projects.length === 0)
              ? "프로젝트 정보를 불러오는 중입니다."
              : "프로젝트를 찾을 수 없거나 접근 권한이 없습니다."}
          </p>
        </section>
      )}

      {role === "admin" && page.kind === "home" && <AdminConsole auth={auth} />}
    </main>
  );
}

function HomePage({
  auth,
  role,
  session,
  systemSummary,
  publicProjects,
  projects,
  loading,
  onOpenProject,
  onCreated
}: {
  auth: AuthHeaders;
  role: Role;
  session: AuthSession;
  systemSummary: SystemSummary | null;
  publicProjects: Project[];
  projects: Project[];
  loading: boolean;
  onOpenProject: (project: string) => void;
  onCreated: (project: string) => Promise<void>;
}) {
  const [tab, setTab] = useState<"all" | "mine" | "create">(() => role === "visitor" ? "all" : "mine");
  const owned = useMemo(() => new Set(projects.map((project) => project.name)), [projects]);

  useEffect(() => {
    setTab(role === "visitor" ? "all" : "mine");
  }, [role, session?.id]);

  return (
    <div className="homeSurface">
      <nav className="homeTabs" aria-label="console sections">
        <button className={tab === "all" ? "active" : ""} onClick={() => setTab("all")}>전체 프로젝트</button>
        <button className={tab === "mine" ? "active" : ""} onClick={() => setTab("mine")}>내 프로젝트</button>
        <button className={tab === "create" ? "active" : ""} onClick={() => setTab("create")}>새 프로젝트</button>
      </nav>
      <div className="homeDashboard">
        {tab === "all" && (
          <ProjectList
            title="전체 프로젝트"
            description="현재 서버에 등록된 프로젝트입니다. 로그인 후 권한이 있는 프로젝트만 상세로 들어갈 수 있습니다."
            role={role}
            projects={publicProjects}
            ownedProjects={owned}
            loading={false}
            readOnly={role === "visitor"}
            onSelect={onOpenProject}
          />
        )}
        {tab === "mine" && (
          <ProjectList
            title="내 프로젝트"
            description={role === "visitor" ? "로그인하면 접근 가능한 프로젝트가 표시됩니다." : "상세 운영과 AI 에이전트를 사용할 수 있는 프로젝트입니다."}
            role={role}
            projects={projects}
            ownedProjects={owned}
            loading={loading}
            readOnly={role === "visitor"}
            onSelect={onOpenProject}
          />
        )}
        {tab === "create" && (
          <LandingCard auth={auth} onCreated={onCreated} />
        )}
        <aside className="homeRail">
          <SystemOverview summary={systemSummary} role={role} />
          {tab !== "create" && <LandingCard auth={auth} onCreated={onCreated} compact />}
        </aside>
      </div>
    </div>
  );
}

function LoginPanel({
  session,
  onLogin,
  onLogout
}: {
  session: AuthSession;
  onLogin: (session: NonNullable<AuthSession>) => void;
  onLogout: () => void;
}) {
  const [userId, setUserId] = useState("local-user");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function login() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId.trim(), password })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "로그인에 실패했습니다.");
      onLogin({
        id: String(data.id),
        role: String(data.role || "user") as Role,
        name: data.name ? String(data.name) : undefined
      });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="loginPanel">
      <span>로그인</span>
      {session ? (
        <>
          <strong>{session.name || session.id}</strong>
          <small>{session.role}</small>
          <button className="secondaryButton" onClick={onLogout}>로그아웃</button>
        </>
      ) : (
        <form
          className="loginForm"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && userId.trim()) login();
          }}
        >
          <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="user id" autoComplete="username" />
          <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="password" type="password" autoComplete="current-password" />
          <button type="submit" disabled={busy || !userId.trim()}>
            {busy ? "확인 중..." : "로그인"}
          </button>
          <small>기본: local-user / 빈 비밀번호, admin / admin</small>
          {message && <small className="loginError">{message}</small>}
        </form>
      )}
    </aside>
  );
}

function SystemOverview({ summary, role }: { summary: SystemSummary | null; role: Role }) {
  if (role === "visitor") return null;
  const unhealthy = summary?.unhealthy || [];
  const restarting = summary?.restarting || [];
  const attentionCount = unhealthy.length + restarting.length;
  return (
    <section className="systemOverview" aria-label="server capacity">
      <div className="resourceHeader">
        <span>서버 용량</span>
        <strong>{attentionCount ? `${attentionCount} issues` : "정상"}</strong>
      </div>
      <div className="gaugeRow">
        <CircularGauge label="메모리" value={summary?.memory_percent} />
        <CircularGauge label="디스크" value={summary?.disk_percent} />
      </div>
      {attentionCount > 0 && (
        <p className="resourceWarning">
          {unhealthy.length ? `헬스체크 ${unhealthy.length}` : ""}
          {unhealthy.length && restarting.length ? " · " : ""}
          {restarting.length ? `재시작 ${restarting.length}` : ""}
        </p>
      )}
    </section>
  );
}

function CircularGauge({ label, value }: { label: string; value?: number | null }) {
  const safeValue = Math.max(0, Math.min(100, Number(value ?? 0)));
  const level = safeValue >= 90 ? "danger" : safeValue >= 75 ? "warn" : "ok";
  return (
    <div className="gauge">
      <div
        className={`gaugeDial ${level}`}
        style={{ "--value": `${safeValue}%` } as React.CSSProperties}
        aria-label={`${label} ${formatPercent(value)}`}
      >
        <strong>{formatPercent(value)}</strong>
      </div>
      <span>{label}</span>
    </div>
  );
}

function LandingCard({
  auth,
  onCreated,
  compact = false
}: {
  auth: AuthHeaders;
  onCreated: (project: string) => Promise<void>;
  compact?: boolean;
}) {
  const role = auth.role;
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<unknown | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function createProject(approved: boolean) {
    setBusy(true);
    setMessage("");
    try {
      const data = await api<unknown>("/api/projects", auth, {
        method: "POST",
        body: JSON.stringify({ name, approved })
      });
      if (!approved) {
        setPreview(data);
        setMessage("생성 전 미리보기입니다. 확인 후 승인하세요.");
      } else {
        const created = name;
        setPreview(null);
        setName("");
        setMessage("프로젝트를 생성했습니다.");
        await onCreated(created);
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={compact ? "workspace createProject compactCreate" : "workspace createProject"}>
      <div className="workspaceHeader">
        <div>
          <h2>새 프로젝트</h2>
        </div>
      </div>
      <div className="createPanel">
        <input
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            setPreview(null);
          }}
          placeholder="예: horse_race"
          disabled={role === "visitor"}
        />
        <button disabled={!name || busy || role === "visitor"} onClick={() => createProject(false)}>
          미리보기
        </button>
        <button disabled={preview === null || busy || role === "visitor"} onClick={() => createProject(true)}>
          승인 생성
        </button>
      </div>
      {role === "visitor" && <p className="hint">로그인 후 생성할 수 있습니다.</p>}
      {message && <p className="hint">{message}</p>}
      {preview !== null && (
        <div className="previewCard">
          <strong>생성 전 확인</strong>
          <p><code>{name}</code> 프로젝트를 생성합니다.</p>
        </div>
      )}
    </section>
  );
}

function ProjectList({
  title,
  description,
  role,
  projects,
  ownedProjects,
  loading,
  readOnly,
  onSelect
}: {
  title: string;
  description: string;
  role: Role;
  projects: Project[];
  ownedProjects: Set<string>;
  loading: boolean;
  readOnly?: boolean;
  onSelect: (name: string) => void;
}) {
  return (
    <section className="workspace projectBoard">
      <div className="workspaceHeader">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      {loading && <p className="hint">불러오는 중...</p>}
      <div className="projectGrid">
        {projects.map((project) => {
          const canOpen = role === "admin" || ownedProjects.has(project.name);
          const locked = readOnly || !canOpen;
          return (
            <button
              key={project.name}
              className={`projectCard ${locked ? "locked" : ""}`}
              onClick={() => onSelect(project.name)}
              aria-label={locked ? `${project.name} 프로젝트는 로그인 또는 권한이 필요합니다.` : `${project.name} 프로젝트 열기`}
            >
              <span className={`projectCardMeta ${locked ? "locked" : ""}`}>
                {locked ? "locked" : `${project.services?.length || 0} services`}
              </span>
              <strong>{project.name}</strong>
              <span className="projectServiceChips">
                {(project.services || []).slice(0, 4).map((service) => (
                  <span key={service}>{service}</span>
                ))}
                {(project.services || []).length > 4 && <span>+{(project.services || []).length - 4}</span>}
                {!(project.services || []).length && <span>서비스 없음</span>}
              </span>
            </button>
          );
        })}
        {projects.length === 0 && <p className="hint">표시할 프로젝트가 없습니다.</p>}
      </div>
    </section>
  );
}

function ProjectWorkspace({
  auth,
  project,
  onBack,
  onRefresh
}: {
  auth: AuthHeaders;
  project: Project;
  onBack: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [quickPrompt, setQuickPrompt] = useState<QuickPrompt | null>(null);
  const [runtimeServices, setRuntimeServices] = useState<Record<string, ServiceRuntime>>({});
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState("");
  const [actionBusy, setActionBusy] = useState<string>("");
  const [actionOutput, setActionOutput] = useState<ServiceActionOutput | null>(null);
  const services = project.services || [];
  const runtimeList = Object.values(runtimeServices);
  const summary = projectRuntimeSummary(runtimeList);

  async function refreshRuntime() {
    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      const data = await api<{ result?: { services?: ServiceRuntime[] } }>(`/api/projects/${project.name}/execute`, auth, {
        method: "POST",
        body: JSON.stringify({
          skill: "service.status",
          arguments: {},
          approved: true
        })
      });
      const next: Record<string, ServiceRuntime> = {};
      for (const item of data.result?.services || []) {
        next[item.service] = item;
      }
      setRuntimeServices(next);
    } catch (err) {
      setRuntimeError(err instanceof Error ? err.message : String(err));
    } finally {
      setRuntimeLoading(false);
    }
  }

  useEffect(() => {
    refreshRuntime();
  }, [project.name]);

  async function refreshWorkspace() {
    await Promise.all([onRefresh(), refreshRuntime()]);
  }

  async function runServiceAction(
    service: string,
    action: "logs" | "start" | "stop" | "restart" | "redeploy"
  ) {
    const busyKey = `${service}:${action}`;
    setActionBusy(busyKey);
    setActionOutput(null);
    try {
      const body =
        action === "logs"
          ? { skill: "service.logs", arguments: { service, lines: 80 }, approved: true }
          : action === "redeploy"
            ? { skill: "service.redeploy", arguments: { service }, approved: true }
            : { skill: "service.control", arguments: { service, action }, approved: true };
      const data = await api<Record<string, unknown>>(`/api/projects/${project.name}/execute`, auth, {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (action === "logs") {
        const result = isRecord(data.result) ? data.result : {};
        setActionOutput({
          title: `${service} 로그`,
          text: String(result.logs || "로그가 비어 있습니다."),
          tone: "ok"
        });
      } else {
        setActionOutput({
          title: `${service} ${serviceActionLabel(action)}`,
          text: `${serviceActionLabel(action)} 작업을 실행했고 상태를 다시 확인했습니다.`,
          tone: "ok"
        });
        await Promise.all([onRefresh(), refreshRuntime()]);
      }
    } catch (err) {
      setActionOutput({
        title: `${service} ${serviceActionLabel(action)} 실패`,
        text: err instanceof Error ? err.message : String(err),
        tone: "error"
      });
    } finally {
      setActionBusy("");
    }
  }

  return (
    <section className="workspace detailPage">
      <div className="workspaceHeader detailHeader">
        <div>
          <h2>{project.name}</h2>
          <p>이 프로젝트 안의 서비스만 조회하고 조작합니다.</p>
        </div>
        <div className="headerActions">
          <button onClick={() => setQuickPrompt(makeQuickPrompt("새 서비스 배포하고 싶어"))}>새 서비스 배포</button>
          <button className="secondaryButton" onClick={onBack}>메인으로</button>
          <button onClick={refreshWorkspace} disabled={runtimeLoading}>{runtimeLoading ? "확인 중..." : "새로고침"}</button>
        </div>
      </div>
      {runtimeError && <div className="error compactError">{runtimeError}</div>}
      <ProjectCapacity summary={summary} loading={runtimeLoading} />

      <div className="projectDetailLayout">
        <main className="operationsPanel">
          <div className="panelHeader">
            <div>
              <h3>서비스 운영</h3>
              <p>상태와 URL을 확인하고 로그, 시작·중지, 재시작, 재배포를 바로 실행합니다.</p>
            </div>
            <span className="panelMeta">{services.length} services</span>
          </div>
          {actionOutput ? <ActionOutput output={actionOutput} onClose={() => setActionOutput(null)} /> : null}
          {services.length > 0 ? (
            <div className="serviceTableWrap">
              <table className="serviceTable">
                <thead>
                  <tr>
                    <th>서비스</th>
                    <th>상태</th>
                    <th>접속</th>
                    <th>포트</th>
                    <th>메모리</th>
                    <th>액션</th>
                  </tr>
                </thead>
                <tbody>
                  {services.map((service) => (
                    <ServiceRow
                      key={service}
                      service={service}
                      runtime={runtimeServices[service]}
                      loading={runtimeLoading && !runtimeServices[service]}
                      busyAction={actionBusy.startsWith(`${service}:`) ? actionBusy.split(":")[1] ?? "" : ""}
                      onAction={(action) => runServiceAction(service, action)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="emptyState">
              <strong>아직 등록된 서비스가 없습니다.</strong>
              <p>새 서비스 배포 버튼을 눌러 GitHub 저장소와 프레임워크를 입력하면 CLI 검증 후 배포 계획을 확인할 수 있습니다.</p>
              <button onClick={() => setQuickPrompt(makeQuickPrompt("새 서비스 배포하고 싶어"))}>첫 서비스 배포</button>
            </div>
          )}
        </main>

        <aside className="agentSidePanel">
          <AgentPanel auth={auth} project={project.name} services={services} quickPrompt={quickPrompt} />
        </aside>
      </div>
    </section>
  );
}

function formatPort(runtime?: ServiceRuntime) {
  const ports = runtime?.container?.ports || [];
  if (ports.length > 0) {
    return ports.map((port) => `${port.host}→${port.container}`).join(", ");
  }
  const configured = runtime?.configured_ports || [];
  return configured.length > 0 ? configured.join(", ") : "내부";
}

function formatMemory(memory?: RuntimeMemory | null) {
  if (!memory?.usage_mb) return "확인 전";
  const limit = memory.limit_mb ? ` / ${memory.limit_mb}MB` : "";
  const percent = memory.percent != null ? ` (${memory.percent}%)` : "";
  return `${memory.usage_mb}MB${limit}${percent}`;
}

function formatPercent(value?: number | null) {
  return typeof value === "number" ? `${value}%` : "-";
}

function firstHostPort(runtime?: ServiceRuntime) {
  return (runtime?.container?.ports || []).find((port) => port.host)?.host;
}

function publicUrl(runtime?: ServiceRuntime) {
  if (!runtime?.frontend) return "";
  const hostPort = firstHostPort(runtime);
  if (!hostPort) return "";
  return `${window.location.protocol}//${window.location.hostname}:${hostPort}`;
}

function projectRuntimeSummary(services: ServiceRuntime[]) {
  const running = services.filter((item) => item.container?.status === "running").length;
  const memory = services.reduce((sum, item) => sum + (item.container?.memory?.usage_mb || 0), 0);
  const publicCount = services.filter((item) => publicUrl(item)).length;
  return {
    running,
    total: services.length,
    memory: Math.round(memory * 10) / 10,
    publicCount
  };
}

function statusLabel(status?: string, health?: string | null) {
  if (!status) return "unknown";
  return health ? `${status} · ${health}` : status;
}

function serviceActionLabel(action: string) {
  const labels: Record<string, string> = {
    logs: "로그 조회",
    start: "시작",
    stop: "중지",
    restart: "재시작",
    redeploy: "재배포"
  };
  return labels[action] || action;
}

function ProjectCapacity({
  summary,
  loading
}: {
  summary: ReturnType<typeof projectRuntimeSummary>;
  loading: boolean;
}) {
  return (
    <div className="capacityStrip">
      <div>
        <span>실행 상태</span>
        <strong>{loading ? "확인 중" : `${summary.running}/${summary.total} running`}</strong>
      </div>
      <div>
        <span>메모리</span>
        <strong>{summary.memory}MB</strong>
      </div>
      <div>
        <span>외부 URL</span>
        <strong>{summary.publicCount}</strong>
      </div>
    </div>
  );
}

function ActionOutput({ output, onClose }: { output: ServiceActionOutput; onClose: () => void }) {
  return (
    <div className={`actionOutput ${output.tone || "ok"}`}>
      <div>
        <strong>{output.title}</strong>
        <button className="secondaryButton" onClick={onClose}>닫기</button>
      </div>
      <pre>{output.text}</pre>
    </div>
  );
}

function serviceKind(runtime?: ServiceRuntime) {
  if (!runtime) return "확인 전";
  return runtime.frontend ? "Frontend" : "Internal";
}

function serviceStatusTone(status: string) {
  if (status === "running") return "";
  if (status === "loading" || status === "unknown") return "neutral";
  return "warning";
}

function ServiceRow({
  service,
  runtime,
  loading,
  busyAction,
  onAction
}: {
  service: string;
  runtime?: ServiceRuntime;
  loading: boolean;
  busyAction: string;
  onAction: (action: "logs" | "start" | "stop" | "restart" | "redeploy") => void;
}) {
  const container = runtime?.container;
  const status = container?.status || (loading ? "loading" : "unknown");
  const isRunning = status === "running";
  const url = publicUrl(runtime);
  return (
    <tr>
      <td>
        <div className="serviceIdentity">
          <strong>{service}</strong>
          <span>{serviceKind(runtime)}</span>
        </div>
      </td>
      <td>
        <span className={`pill ${serviceStatusTone(status)}`}>{statusLabel(status, container?.health)}</span>
      </td>
      <td>
        {url ? (
          <a className="serviceUrl" href={url} target="_blank" rel="noreferrer">바로가기</a>
        ) : (
          <span className="mutedUrl">{runtime?.frontend ? "공개 URL 없음" : "내부 통신"}</span>
        )}
      </td>
      <td>{formatPort(runtime)}</td>
      <td>{formatMemory(container?.memory)}</td>
      <td>
        <div className="serviceActions compactActions">
          <button onClick={() => onAction("logs")} disabled={Boolean(busyAction)}>
            {busyAction === "logs" ? "조회 중" : "로그"}
          </button>
          <button onClick={() => onAction("start")} disabled={Boolean(busyAction) || isRunning}>
            {busyAction === "start" ? "시작 중" : "시작"}
          </button>
          <button className="dangerButton" onClick={() => onAction("stop")} disabled={Boolean(busyAction) || !isRunning}>
            {busyAction === "stop" ? "중지 중" : "중지"}
          </button>
          <button onClick={() => onAction("restart")} disabled={Boolean(busyAction) || !container}>
            {busyAction === "restart" ? "재시작 중" : "재시작"}
          </button>
          <button onClick={() => onAction("redeploy")} disabled={Boolean(busyAction)}>
            {busyAction === "redeploy" ? "배포 중" : "재배포"}
          </button>
        </div>
      </td>
    </tr>
  );
}

function AgentPanel({
  auth,
  project,
  services,
  quickPrompt
}: {
  auth: AuthHeaders;
  project: string;
  services: string[];
  quickPrompt?: QuickPrompt | null;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId] = useState(() => newSessionId());
  const [context, setContext] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [showDeployGuide, setShowDeployGuide] = useState(false);
  const [deployGuide, setDeployGuide] = useState<DeployGuideState>({
    service: "",
    repoUrl: "",
    framework: "",
    isWeb: "web",
    useDefaults: true,
    hostPort: "",
    envNames: ""
  });
  const [deployGuideErrors, setDeployGuideErrors] = useState<Record<string, string>>({});
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!quickPrompt) return;
    if (quickPrompt.text.includes("서비스 배포")) {
      setShowDeployGuide(true);
      setInput("");
      return;
    }
    setInput(quickPrompt.text);
  }, [quickPrompt?.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const examples = services.length > 0
    ? `예: “서비스 목록 보여줘”, “${services[0]} 상태 확인해줘”, “새 서비스 배포하고 싶어”`
    : "예: “새 서비스 배포하고 싶어”, “지원하는 프레임워크 보여줘”, “배포에 필요한 정보 알려줘”";

  function updateApproval(index: number, status: ApprovalRequest["status"]) {
    setMessages((items) =>
      items.map((item, itemIndex) =>
        itemIndex === index && item.approval
          ? { ...item, approval: { ...item.approval, status } }
          : item
      )
    );
  }

  async function approve(index: number, approval: ApprovalRequest) {
    updateApproval(index, "executing");
    setBusy(true);
    try {
      const data = await api<Record<string, unknown>>(`/api/projects/${project}/execute`, auth, {
        method: "POST",
        body: JSON.stringify({
          skill: approval.skill,
          arguments: approval.arguments,
          approved: true,
          session_id: sessionId,
          resume: approval.resume
        })
      });
      updateApproval(index, "done");
      setMessages((items) => [...items, { from: "agent", text: summarizeExecution(data) }]);
    } catch (err) {
      updateApproval(index, "failed");
      setMessages((items) => [...items, { from: "agent", text: err instanceof Error ? err.message : String(err) }]);
    } finally {
      setBusy(false);
    }
  }

  async function sendText(text: string, displayText = text) {
    if (!text.trim()) return;
    setInput("");
    setMessages((items) => [...items, { from: "user", text: displayText }]);
    setBusy(true);
    try {
      const data = await api<AgentResponse>(`/api/projects/${project}/chat`, auth, {
        method: "POST",
        body: JSON.stringify({ message: text, session_id: sessionId, context })
      });
      if (data.context && typeof data.context === "object") {
        setContext(data.context as Record<string, unknown>);
      }
      if (isApprovalAgentResponse(data)) {
        setMessages((items) => [
          ...items,
          {
            from: "agent",
            text: summarizeApproval(data),
            approval: {
              skill: data.skill,
              arguments: data.arguments,
              preview: data.preview,
              resume: data.resume,
              status: "pending"
            }
          }
        ]);
        return;
      }
      if (isDeployFormHint(data)) {
        openDeployGuideFromResponse(data);
        return;
      }
      setMessages((items) => [...items, { from: "agent", text: String(data.message || "응답을 받았습니다.") }]);
    } catch (err) {
      setMessages((items) => [...items, { from: "agent", text: err instanceof Error ? err.message : String(err) }]);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!input.trim()) return;
    await sendText(input.trim());
  }

  function updateDeployGuide(patch: Partial<DeployGuideState>) {
    setDeployGuideErrors((current) => {
      const next = { ...current };
      if ("service" in patch) delete next.service;
      if ("repoUrl" in patch) delete next.repo_url;
      if ("framework" in patch) delete next.framework;
      if ("hostPort" in patch) delete next.host_port;
      if ("envNames" in patch) delete next.environment_names;
      return next;
    });
    setDeployGuide((current) => ({ ...current, ...patch }));
  }

  function openDeployGuideFromResponse(data: AgentResponse) {
    const args = data.ui?.arguments || data.arguments || {};
    const fieldErrors = data.ui?.field_errors || data.field_errors || {};
    setDeployGuide((current) => ({
      ...current,
      service: typeof args.service === "string" ? args.service : current.service,
      repoUrl: typeof args.repo_url === "string" ? args.repo_url : current.repoUrl,
      framework: normalizeFramework(args.framework) || current.framework,
      isWeb: args.is_web === false ? "internal" : current.isWeb,
      hostPort:
        typeof args.host_port === "number" || typeof args.host_port === "string"
          ? String(args.host_port)
          : current.hostPort,
      envNames: Array.isArray(args.environment_names)
        ? args.environment_names.map(String).join(", ")
        : current.envNames
    }));
    setDeployGuideErrors(fieldErrors);
    setShowDeployGuide(true);
    setMessages((items) => [
      ...items,
      { from: "agent", text: String(data.message || "새 서비스 배포는 아래 입력 카드에서 진행할게요.") }
    ]);
  }

  async function submitDeployGuide() {
    setDeployGuideErrors({});
    const selectedFramework = frameworkOptions.find((item) => item.id === deployGuide.framework);
    const envNames = deployGuide.envNames
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const optionalParts = deployGuide.useDefaults
      ? ["선택 설정은 기본값으로 진행해도 돼."]
      : [
          deployGuide.hostPort ? `호스트 포트는 ${deployGuide.hostPort}.` : "호스트 포트는 자동 추천해줘.",
          envNames.length > 0 ? `환경변수 이름은 ${envNames.join(", ")}.` : "환경변수는 지금 없어."
        ];
    const text = [
      `${project} 프로젝트에 새 서비스를 배포하고 싶어.`,
      `서비스 이름은 ${deployGuide.service}.`,
      `GitHub 저장소는 ${deployGuide.repoUrl}.`,
      `프레임워크는 ${selectedFramework?.label || deployGuide.framework} (${deployGuide.framework}).`,
      deployGuide.isWeb === "web"
        ? "브라우저에서 접속하는 웹서비스야. 프론트엔드면 바로가기 URL도 보여줘."
        : "외부 URL이 필요 없는 내부 서비스야.",
      ...optionalParts,
      "이 정보로 CLI 검증을 먼저 하고, 실행 계획을 자연어로 보여준 다음 승인받아 진행해줘."
    ].join(" ");
    await sendText(text);
  }

  const deployGuideReady = Boolean(
    deployGuide.service.trim()
    && deployGuide.repoUrl.trim()
    && /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+(?:\.git)?$/.test(deployGuide.repoUrl.trim())
    && deployGuide.framework
    && (deployGuide.useDefaults || !deployGuide.hostPort.trim() || /^\d{2,5}$/.test(deployGuide.hostPort.trim()))
  );

  return (
    <section className="agentPanel">
      <div className="agentTitle">
        <div>
          <h3>AI 작업</h3>
          <p>배포 · 상태 · 로그 · 재배포</p>
        </div>
      </div>
      <div className="agentShortcuts">
        <button className={showDeployGuide ? "active" : ""} onClick={() => setShowDeployGuide((value) => !value)}>
          새 서비스 배포
        </button>
        <button className="secondaryButton" onClick={() => sendText("서비스 목록 보여줘")} disabled={busy}>
          상태 요약
        </button>
        <button className="secondaryButton" onClick={() => sendText("지원하는 프레임워크와 각각 언제 쓰는지 알려줘")} disabled={busy}>
          프레임워크 도움말
        </button>
      </div>
      <div className="messages">
        {messages.length === 0 && (
          <div className="emptyChat">
            {examples}
          </div>
        )}
        {messages.map((message, index) => (
          <div className={`bubble ${message.from}`} key={index}>
            <MessageText text={message.text} />
            {message.approval ? (
              <ApprovalCard
                approval={message.approval}
                onApprove={() => approve(index, message.approval!)}
                onCancel={() => updateApproval(index, "failed")}
                busy={busy}
              />
            ) : null}
          </div>
        ))}
        {showDeployGuide ? (
          <DeployGuideCard
            busy={busy}
            deployGuide={deployGuide}
            errors={deployGuideErrors}
            deployGuideReady={deployGuideReady}
            onChange={updateDeployGuide}
            onSubmit={submitDeployGuide}
          />
        ) : null}
        {busy && (
          <div className="bubble agent loadingBubble">
            <span className="spinner" />
            <p>AI가 응답을 준비 중입니다...</p>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="row">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && send()}
          placeholder={`${project} 안에서 서비스 배포/상태/로그를 요청`}
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>보내기</button>
      </div>
    </section>
  );
}

function DeployGuideCard({
  busy,
  deployGuide,
  errors,
  deployGuideReady,
  onChange,
  onSubmit
}: {
  busy: boolean;
  deployGuide: DeployGuideState;
  errors: Record<string, string>;
  deployGuideReady: boolean;
  onChange: (patch: Partial<DeployGuideState>) => void;
  onSubmit: () => void;
}) {
  const repoUrlLooksValid = !deployGuide.repoUrl.trim()
    || /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+(?:\.git)?$/.test(deployGuide.repoUrl.trim());
  const repoUrlError = errors.repo_url || (!repoUrlLooksValid ? "https://github.com/<owner>/<repo> 형식의 공개 저장소 URL을 입력하세요." : "");
  return (
    <div className="guidedDeploy chatGuidedDeploy">
      <div className="guidedHeader">
        <div>
          <p className="formKicker">필수 정보</p>
          <strong>새 서비스 배포를 위해 몇 가지만 확인할게요</strong>
          <p>선택지는 버튼으로 고르고, 필요한 값만 직접 입력하세요. 필수값이 채워지면 계속 진행할 수 있습니다.</p>
        </div>
        <span className="pill">LLM + CLI guard</span>
      </div>
      <div className="questionBlock">
        <label>
          <span>서비스 이름이 무엇인가요? <em>필수</em></span>
          <small>프로젝트 안에서 구분할 이름입니다. 예: horse_front, api_server</small>
          <input
            value={deployGuide.service}
            onChange={(event) => onChange({ service: event.target.value })}
            placeholder="예: horse_front"
            disabled={busy}
          />
          {errors.service ? <small className="fieldError">{errors.service}</small> : null}
        </label>
      </div>
      <div className="questionBlock">
        <label>
          <span>GitHub 저장소 URL은 무엇인가요? <em>필수</em></span>
          <small>공개 HTTPS 저장소만 검증할 수 있습니다.</small>
          <input
            value={deployGuide.repoUrl}
            onChange={(event) => onChange({ repoUrl: event.target.value })}
            placeholder="https://github.com/owner/repo"
            disabled={busy}
          />
          {repoUrlError ? <small className="fieldError">{repoUrlError}</small> : null}
        </label>
      </div>
      <div className="questionBlock">
        <span>어떤 프레임워크로 배포할까요? <em>필수</em></span>
        <small>잘 모르겠으면 저장소 구조에 가장 가까운 항목을 고르세요. 기존 Dockerfile이 있으면 그대로 사용할 수도 있습니다.</small>
        <div className="choiceGrid">
          {frameworkOptions.map((item) => (
            <button
              key={item.id}
              type="button"
              className={deployGuide.framework === item.id ? "choice active" : "choice"}
              onClick={() => onChange({ framework: item.id })}
              disabled={busy}
            >
              <strong>{item.label}</strong>
              <small>{item.hint}</small>
            </button>
          ))}
        </div>
        {errors.framework ? <small className="fieldError">{errors.framework}</small> : null}
      </div>
      <div className="guidedGrid compact">
        <div className="questionBlock compactQuestion">
          <span>외부에서 접속하는 웹서비스인가요?</span>
          <div className="segmented">
            <button
              type="button"
              className={deployGuide.isWeb === "web" ? "active" : ""}
              onClick={() => onChange({ isWeb: "web" })}
              disabled={busy}
            >
              웹 바로가기 필요
            </button>
            <button
              type="button"
              className={deployGuide.isWeb === "internal" ? "active" : ""}
              onClick={() => onChange({ isWeb: "internal" })}
              disabled={busy}
            >
              내부 서비스
            </button>
          </div>
        </div>
        <div className="questionBlock compactQuestion">
          <span>포트·환경변수는 어떻게 할까요?</span>
          <div className="segmented">
            <button
              type="button"
              className={deployGuide.useDefaults ? "active" : ""}
              onClick={() => onChange({ useDefaults: true })}
              disabled={busy}
            >
              기본값 사용
            </button>
            <button
              type="button"
              className={!deployGuide.useDefaults ? "active" : ""}
              onClick={() => onChange({ useDefaults: false })}
              disabled={busy}
            >
              직접 지정
            </button>
          </div>
        </div>
      </div>
      {!deployGuide.useDefaults ? (
        <div className="guidedGrid">
          <label className="questionBlock">
            <span>호스트 포트</span>
            <small>비워두면 9000~9100 범위에서 자동 추천합니다.</small>
            <input
              value={deployGuide.hostPort}
              onChange={(event) => onChange({ hostPort: event.target.value })}
              placeholder="비우면 9000~9100 자동 추천"
              disabled={busy}
            />
            {errors.host_port ? <small className="fieldError">{errors.host_port}</small> : null}
          </label>
          <label className="questionBlock">
            <span>환경변수 이름</span>
            <small>실제 비밀값은 LLM에 보내지 않습니다. 이름만 쉼표로 적어주세요.</small>
            <input
              value={deployGuide.envNames}
              onChange={(event) => onChange({ envNames: event.target.value })}
              placeholder="예: DATABASE_URL, API_KEY"
              disabled={busy}
            />
          </label>
        </div>
      ) : null}
      <div className="guidedFooter">
        <p>{deployGuideReady ? "필수 정보가 채워졌습니다. 제출하면 LLM이 의도를 정리하고 CLI가 실행 계획을 검증합니다." : "서비스 이름, GitHub URL, 프레임워크를 먼저 채워주세요."}</p>
        <button onClick={onSubmit} disabled={busy || !deployGuideReady}>
          계속
        </button>
      </div>
    </div>
  );
}

function ApprovalCard({
  approval,
  onApprove,
  onCancel,
  busy
}: {
  approval: ApprovalRequest;
  onApprove: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const args = approval.arguments;
  const preview = isRecord(approval.preview) ? approval.preview : {};
  const command = String(preview.command || preview.action || labelSkill(approval.skill));
  const steps = previewSteps(approval.preview);
  const disabled = busy || approval.status !== "pending";

  return (
    <div className="approvalCard">
      <div className="approvalHeader">
        <strong>{labelSkill(approval.skill)}</strong>
        <span className={`approvalStatus ${approval.status}`}>{approval.status}</span>
      </div>
      <dl>
        <div>
          <dt>작업</dt>
          <dd>{command}</dd>
        </div>
        <div>
          <dt>프로젝트</dt>
          <dd>{String(args.project || preview.project || "-")}</dd>
        </div>
        {args.service ? (
          <div>
            <dt>서비스</dt>
            <dd>{String(args.service)}</dd>
          </div>
        ) : null}
        {args.framework ? (
          <div>
            <dt>프레임워크</dt>
            <dd>{String(args.framework)}</dd>
          </div>
        ) : null}
        {args.repo_url ? (
          <div>
            <dt>저장소</dt>
            <dd>{String(args.repo_url)}</dd>
          </div>
        ) : null}
      </dl>
      {steps.length > 0 ? (
        <div className="approvalSteps">
          <strong>진행 예정</strong>
          <ol>
            {steps.map((step) => <li key={step}>{step}</li>)}
          </ol>
        </div>
      ) : null}
      <div className="approvalActions">
        <button onClick={onApprove} disabled={disabled}>
          {approval.status === "executing" ? "실행 중..." : "승인하고 실행"}
        </button>
        <button className="secondaryButton" onClick={onCancel} disabled={disabled}>
          취소
        </button>
      </div>
    </div>
  );
}

function AdminConsole({ auth }: { auth: AuthHeaders }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId] = useState(() => newSessionId());

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    setMessages((items) => [...items, { from: "user", text }]);
    try {
      const data = await api<Record<string, unknown>>("/api/admin/chat", auth, {
        method: "POST",
        body: JSON.stringify({ message: text, session_id: sessionId })
      });
      setMessages((items) => [...items, { from: "agent", text: String(data.message || "응답을 받았습니다.") }]);
    } catch (err) {
      setMessages((items) => [...items, { from: "agent", text: err instanceof Error ? err.message : String(err) }]);
    }
  }

  return (
    <section className="workspace admin">
      <div className="workspaceHeader">
        <div>
          <h2>루트 AI 에이전트</h2>
        </div>
      </div>
      <div className="agentPanel">
        <div className="messages">
          {messages.map((message, index) => (
            <div className={`bubble ${message.from}`} key={index}>
              <MessageText text={message.text} />
            </div>
          ))}
        </div>
        <div className="row">
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="전체 서버/프로젝트 관리 명령" />
          <button onClick={send}>보내기</button>
        </div>
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
