import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Bot,
  ClipboardCheck,
  FileText,
  HelpCircle,
  ListChecks,
  Loader2,
  MessageSquareText,
  Rocket,
  RotateCcw,
  Search,
  Send,
  ServerCog,
  ShieldCheck,
  Sparkles,
  type LucideIcon
} from "lucide-react";
import "./styles.css";

type Role = "visitor" | "user" | "admin";
type Page = { kind: "home" } | { kind: "project"; project: string };
type QuickPrompt = { id: number; text: string };
type AgentScope = "root" | "project";
type AgentSuggestion = {
  label: string;
  text: string;
  description?: string;
  icon: LucideIcon;
  form?: boolean;
  tone?: "primary" | "default";
};
type AgentSuggestionGroup = {
  title: string;
  prompts: AgentSuggestion[];
};
type FrameworkId =
  | "auto"
  | "static"
  | "vite"
  | "react"
  | "nextjs"
  | "express"
  | "fastapi"
  | "flask"
  | "django"
  | "spring-maven"
  | "spring-gradle"
  | "go"
  | "existing";

type Project = {
  name: string;
  services?: string[];
  service_summaries?: ProjectServiceSummary[];
  frameworks?: string[];
  running_count?: number;
  service_count?: number;
  attention_count?: number;
  memory_total_mb?: number;
  public_urls?: ProjectPublicUrl[];
  last_deployed_at?: string | null;
  runtime_error?: string | null;
};

type PublicCatalog = {
  projects?: Project[];
};

type ProjectPublicUrl = {
  service?: string;
  host_port?: number | string | null;
};

type ProjectServiceSummary = {
  name?: string;
  service?: string;
  framework?: string | null;
  framework_label?: string | null;
  repo_url?: string | null;
  frontend?: boolean;
  configured_ports?: unknown[];
  host_port?: number | string | null;
  container_port?: number | string | null;
  last_deployed_at?: string | null;
  status?: string;
  health?: string | null;
  memory_mb?: number | null;
  memory_limit_mb?: number | null;
  memory_percent?: number | null;
  runtime_error?: string | null;
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
  host_port?: number | string | null;
  container?: RuntimeContainer | null;
};

type SystemSummary = {
  docker?: boolean;
  containers?: number;
  running?: number;
  disk_percent?: number;
  disk_free_mb?: number;
  memory_percent?: number;
  swap_used_mb?: number;
  swap_percent?: number;
  performance_warnings?: string[];
  unhealthy?: string[];
  restarting?: string[];
};

type ServiceActionOutput = {
  title: string;
  text: string;
  tone?: "ok" | "warn" | "error";
};

type ServiceAction = "logs" | "start" | "stop" | "restart" | "redeploy";

type PendingServiceAction = {
  service: string;
  action: Exclude<ServiceAction, "logs" | "start">;
};

type AuthSession = {
  id: string;
  role: Role;
  name?: string;
  token: string;
} | null;

type AuthHeaders = {
  role: Role;
  userId: string;
  token: string;
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
  stage?: string;
  arguments?: Record<string, unknown>;
  missing?: Array<Record<string, unknown>>;
  field_errors?: Record<string, string>;
  review?: {
    title?: string;
    summary?: string;
    checks?: string[];
    steps?: string[];
    impact?: string[];
  };
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

const GITHUB_REPO_URL_PATTERN = /^https:\/\/github\.com\/[^/\s]+\/[^/\s/]+(?:\.git)?\/?$/;

const frameworkOptions: Array<{
  id: FrameworkId;
  label: string;
  hint: string;
}> = [
  { id: "auto", label: "자동 감지", hint: "저장소를 검증해 가장 맞는 런타임 추천" },
  { id: "static", label: "Vanilla JS / Static", hint: "HTML/CSS/JS를 빌드 없이 서빙" },
  { id: "vite", label: "Vite", hint: "React/Vue/Svelte Vite 앱" },
  { id: "react", label: "Create React App", hint: "CRA 기반 프론트엔드" },
  { id: "nextjs", label: "Next.js", hint: "Next.js 앱" },
  { id: "express", label: "Express / Node", hint: "Node.js 웹 서버" },
  { id: "fastapi", label: "FastAPI", hint: "Python FastAPI 백엔드" },
  { id: "flask", label: "Flask", hint: "Python Flask 백엔드" },
  { id: "django", label: "Django", hint: "Python Django 백엔드" },
  { id: "spring-maven", label: "Spring Maven", hint: "Java Spring Boot Maven" },
  { id: "spring-gradle", label: "Spring Gradle", hint: "Java Spring Boot Gradle" },
  { id: "go", label: "Go", hint: "Go 웹 서비스" },
  { id: "existing", label: "기존 Dockerfile", hint: "저장소의 Dockerfile 그대로 사용" }
];

const visitorAuth: AuthHeaders = {
  role: "visitor",
  userId: "",
  token: ""
};

const SESSION_STORAGE_KEY = "cloud-platform-console-session";

// The role travelled in a header the browser wrote, so the server had only the
// caller's word for it. It now sends the token issued at login and the server
// looks the role up itself.
const authHeaders = (auth: AuthHeaders) => ({
  "Content-Type": "application/json",
  ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {})
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
    "spring-gradle": "spring-gradle",
    gradle: "spring-gradle",
    go: "go",
    golang: "go",
    auto: "auto",
    detect: "auto",
    "자동 감지": "auto",
    existing: "existing",
    dockerfile: "existing"
  };
  return aliases[raw] || "";
}

function isDeployFormHint(data: AgentResponse) {
  return (data.ui?.type === "form" && data.ui.form === "service.deploy") || data.ui?.type === "deploy_form";
}

function loadStoredSession(): AuthSession {
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

function storeSession(session: NonNullable<AuthSession>) {
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

function clearStoredSession() {
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}


function labelSkill(skill?: string) {
  const labels: Record<string, string> = {
    "project.create": "프로젝트 생성",
    "project.list": "프로젝트 목록 조회",
    "server.health": "서버 상태 점검",
    "service.deploy": "새 서비스 배포",
    "service.redeploy": "기존 서비스 재배포",
    "service.logs": "서비스 로그 확인",
    "service.status": "서비스 상태 확인",
    "service.control": "서비스 상태 변경",
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
    "validate the new root-level Dockerfile": "배포에 필요한 Dockerfile을 검증합니다.",
    "atomically swap the service source directory": "기존 서비스 소스와 새 소스를 안전하게 교체합니다.",
    "build a new image and force-recreate only the target service": "대상 서비스만 새 이미지로 다시 빌드합니다.",
    "verify the new container stays running": "새 컨테이너가 정상 실행되는지 확인합니다.",
    "restore the previous source and container if verification fails": "검증 실패 시 이전 상태로 복구합니다."
  };
  return preview.steps
    .filter((item): item is string => typeof item === "string")
    .map((item) => labels[item] || item);
}

function previewStringList(preview: unknown, key: string): string[] {
  if (!isRecord(preview) || !Array.isArray(preview[key])) return [];
  return preview[key].filter((item): item is string => typeof item === "string");
}

function deployFieldLabel(field: string) {
  const labels: Record<string, string> = {
    service: "서비스 이름",
    repo_url: "GitHub 저장소",
    framework: "프레임워크",
    host_port: "호스트 포트",
    environment_names: "환경변수 이름"
  };
  return labels[field] || field;
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
  const [publicProjectsLoading, setPublicProjectsLoading] = useState(true);
  const [publicProjectsError, setPublicProjectsError] = useState("");
  const [systemSummary, setSystemSummary] = useState<SystemSummary | null>(null);
  const [page, setPage] = useState<Page>(() => pageFromLocation());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(() => Boolean(loadStoredSession()));
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const auth = useMemo<AuthHeaders>(
    () => session ? { role: session.role, userId: session.id, token: session.token } : visitorAuth,
    [session]
  );
  const role = auth.role;
  const selectedProject = page.kind === "project"
    ? projects.find((project) => project.name === page.project)
    : undefined;
  // The workspace holds the AI conversation, so it must not be torn down just
  // because a project refresh is in flight or came back without this project
  // for a moment. Stay mounted on the route and fall back to a name-only
  // project until the list has settled and genuinely lacks it.
  const projectSettledMissing =
    page.kind === "project" && projectsLoaded && !loading && !selectedProject;
  const workspaceProject = page.kind === "project" && !projectSettledMissing
    ? selectedProject ?? { name: page.project }
    : undefined;
  const projectNames = useMemo(() => new Set(projects.map((project) => project.name)), [projects]);

  async function refreshPublicProjects(force = false) {
    setPublicProjectsLoading(true);
    setPublicProjectsError("");
    try {
      const response = await fetch("/api/catalog", {
        cache: force ? "reload" : "default",
        headers: force ? { "Cache-Control": "no-cache" } : undefined
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(formatApiError(data.detail) || `Request failed: ${response.status}`);
      setPublicProjects(data.projects || []);
    } catch (err) {
      setPublicProjects([]);
      setPublicProjectsError(err instanceof Error ? err.message : String(err));
    } finally {
      setPublicProjectsLoading(false);
    }
  }

  async function refreshProjects(force = false) {
    if (role === "visitor") {
      setProjects([]);
      setProjectsLoaded(true);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api<{ projects: Project[] }>("/api/projects", auth, {
        headers: force ? { "Cache-Control": "no-cache" } : undefined
      });
      setProjects(data.projects || []);
    } catch (err) {
      if (err instanceof Error && err.name === "SessionExpired") {
        clearStoredSession();
        setSession(null);
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProjectsLoaded(true);
      setLoading(false);
    }
  }

  async function refreshSystemSummary(force = false) {
    if (role === "visitor") {
      setSystemSummary(null);
      return;
    }
    try {
      const data = await api<{ result?: SystemSummary }>("/api/system/summary", auth, {
        headers: force ? { "Cache-Control": "no-cache" } : undefined
      });
      setSystemSummary(data.result || null);
    } catch {
      setSystemSummary(null);
    }
  }

  async function refreshAll(force = false) {
    const tasks = [refreshProjects(force), refreshSystemSummary(force)];
    if (role === "visitor") {
      tasks.push(refreshPublicProjects(force));
    }
    await Promise.all(tasks);
  }

  useEffect(() => {
    if (role === "visitor") {
      refreshPublicProjects();
    }
  }, [role]);

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
          publicProjectsLoading={publicProjectsLoading}
          publicProjectsError={publicProjectsError}
          projects={projects}
          loading={loading}
          onOpenProject={openProject}
          onCreated={async (project) => {
            await refreshAll(true);
            navigate({ kind: "project", project });
          }}
          onLoadPublicProjects={(force = false) => refreshPublicProjects(force)}
        />
      ) : workspaceProject ? (
        <ProjectWorkspace
          auth={auth}
          project={workspaceProject}
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
  publicProjectsLoading,
  publicProjectsError,
  projects,
  loading,
  onOpenProject,
  onCreated,
  onLoadPublicProjects
}: {
  auth: AuthHeaders;
  role: Role;
  session: AuthSession;
  systemSummary: SystemSummary | null;
  publicProjects: Project[];
  publicProjectsLoading: boolean;
  publicProjectsError: string;
  projects: Project[];
  loading: boolean;
  onOpenProject: (project: string) => void;
  onCreated: (project: string) => Promise<void>;
  onLoadPublicProjects: (force?: boolean) => Promise<void>;
}) {
  const [tab, setTab] = useState<"all" | "mine" | "create">(() => role === "visitor" ? "all" : "mine");
  const owned = useMemo(() => new Set(projects.map((project) => project.name)), [projects]);

  useEffect(() => {
    setTab(role === "visitor" ? "all" : "mine");
  }, [role, session?.id]);

  return (
    <div className="homeSurface">
      <aside className="homeSidebar">
        <nav className="homeTabs" aria-label="console sections">
          <button
            className={tab === "all" ? "active" : ""}
            onClick={() => {
              setTab("all");
              void onLoadPublicProjects();
            }}
          >
            전체 프로젝트
          </button>
          <button className={tab === "mine" ? "active" : ""} onClick={() => setTab("mine")}>내 프로젝트</button>
          <button className={tab === "create" ? "active" : ""} onClick={() => setTab("create")}>새 프로젝트</button>
        </nav>
        <span className="homeSessionHint">
          {session ? `${session.name || session.id} · ${session.role}` : "로그인하면 프로젝트를 열 수 있습니다"}
        </span>
      </aside>

      <div className="homeMain">
        <SystemOverview summary={systemSummary} role={role} />

        <div className="homeDashboard">
          {tab === "all" && (
            <ProjectList
              title="전체 프로젝트"
              description="서비스 상태, 프론트 URL, 스택, 최근 배포를 빠르게 확인합니다."
              role={role}
              projects={publicProjects}
              ownedProjects={owned}
              loading={publicProjectsLoading}
              error={publicProjectsError}
              readOnly={role === "visitor"}
              onSelect={onOpenProject}
            />
          )}
          {tab === "mine" && (
            <ProjectList
              title="내 프로젝트"
              description={role === "visitor" ? "로그인하면 운영 가능한 프로젝트가 표시됩니다." : "운영할 프로젝트를 선택하고 바로 작업을 이어갑니다."}
              role={role}
              projects={projects}
              ownedProjects={owned}
              loading={loading}
              error=""
              readOnly={role === "visitor"}
              onSelect={onOpenProject}
            />
          )}
          {tab === "create" && (
            <LandingCard auth={auth} onCreated={onCreated} />
          )}
        </div>
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
      if (!data.token) throw new Error("서버가 세션 토큰을 발급하지 않았습니다.");
      onLogin({
        id: String(data.id),
        role: String(data.role || "user") as Role,
        name: data.name ? String(data.name) : undefined,
        token: String(data.token)
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
          <input
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
            placeholder="user id"
            aria-label="사용자 ID"
            autoComplete="username"
          />
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="password"
            aria-label="비밀번호"
            type="password"
            autoComplete="current-password"
          />
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
  const performanceWarnings = summary?.performance_warnings || [];
  const attentionCount = unhealthy.length + restarting.length;
  const warningParts = [
    unhealthy.length ? `헬스체크 ${unhealthy.length}` : "",
    restarting.length ? `재시작 ${restarting.length}` : "",
    performanceWarnings.includes("disk_low") && summary?.disk_free_mb != null
      ? `디스크 여유 ${summary.disk_free_mb}MB`
      : "",
    performanceWarnings.includes("swap_active") && summary?.swap_used_mb != null
      ? `스왑 ${summary.swap_used_mb}MB 사용`
      : ""
  ].filter(Boolean);
  return (
    <section className="systemOverview" aria-label="server capacity">
      <div className="resourceHeader">
        <span>서버 용량</span>
        <strong>{attentionCount || performanceWarnings.length ? "성능 확인 필요" : "정상"}</strong>
        <small>{summary ? `${summary.running ?? 0}/${summary.containers ?? 0} 컨테이너 실행` : "서버 상태 확인 중"}</small>
      </div>
      <div className="gaugeRow">
        <CircularGauge label="메모리" value={summary?.memory_percent} />
        <CircularGauge label="디스크" value={summary?.disk_percent} />
      </div>
      {warningParts.length > 0 && (
        <p className="resourceWarning">
          {warningParts.join(" · ")}
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
          <p>프로젝트 이름을 정하고 생성 계획을 확인한 뒤 승인합니다.</p>
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
          aria-label="새 프로젝트 이름"
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

function serviceSummaryName(service: ProjectServiceSummary) {
  return String(service.service || service.name || "");
}

function projectServiceNames(project: Project) {
  const fromSummaries = (project.service_summaries || [])
    .map(serviceSummaryName)
    .filter(Boolean);
  return fromSummaries.length ? fromSummaries : (project.services || []);
}

function projectFrameworkLabels(project: Project) {
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

function urlForHostPort(hostPort?: number | string | null) {
  if (hostPort === undefined || hostPort === null || hostPort === "") return "";
  return `${window.location.protocol}//${window.location.hostname}:${hostPort}`;
}

function projectPublicLinks(project: Project) {
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

function formatProjectMemory(project: Project) {
  const value = project.memory_total_mb;
  if (typeof value !== "number") return "메모리 확인 전";
  if (value >= 1024) {
    const gb = value / 1024;
    return `${gb >= 10 ? gb.toFixed(0) : gb.toFixed(1)}GB 사용`;
  }
  return `${value % 1 ? value.toFixed(1) : value.toFixed(0)}MB 사용`;
}

function formatProjectRuntime(project: Project) {
  const total = project.service_count ?? projectServiceNames(project).length;
  const running = project.running_count ?? 0;
  if (total === 0) return "서비스 없음";
  return `${running}/${total} 실행 중`;
}

function formatProjectAttention(project: Project) {
  if (project.runtime_error) return "상태 확인 실패";
  const attention = project.attention_count ?? 0;
  if (attention > 0) return `${attention}개 확인 필요`;
  const total = project.service_count ?? projectServiceNames(project).length;
  return total > 0 ? "정상" : "대기";
}

function projectStackText(project: Project) {
  const frameworks = projectFrameworkLabels(project);
  return frameworks.length ? frameworks.join(" · ") : "기록 없음";
}

function formatRelativeDate(value?: string | null) {
  if (!value) return "기록 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "확인 필요";
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

function ProjectList({
  title,
  description,
  role,
  projects,
  ownedProjects,
  loading,
  error,
  readOnly,
  onSelect
}: {
  title: string;
  description: string;
  role: Role;
  projects: Project[];
  ownedProjects: Set<string>;
  loading: boolean;
  error?: string;
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
      {loading && <ProjectListSkeleton />}
      {error && <p className="inlineError">프로젝트 목록을 불러오지 못했습니다. 잠시 후 새로고침해 주세요. {error}</p>}
      {!loading && (
        <div className="projectIndex" role="list">
          {projects.map((project) => {
            const canOpen = role === "admin" || ownedProjects.has(project.name);
            const locked = readOnly || !canOpen;
            const serviceNames = projectServiceNames(project);
            const publicLinks = projectPublicLinks(project);
            const primaryLink = publicLinks[0];
            return (
              <article
                key={project.name}
                className={`projectRow ${locked ? "locked" : ""}`}
                role="listitem"
              >
                <div className="projectNameCell">
                  <div className="projectTitleLine">
                    <strong>{project.name}</strong>
                    <span className={project.attention_count || project.runtime_error ? "projectState warn" : "projectState"}>
                      {formatProjectAttention(project)}
                    </span>
                  </div>
                  <span className="projectServiceChips">
                    {serviceNames.slice(0, 4).map((service) => (
                      <span key={service}>{service}</span>
                    ))}
                    {serviceNames.length > 4 && <span>+{serviceNames.length - 4}</span>}
                    {!serviceNames.length && <span>서비스 없음</span>}
                  </span>
                  {locked && <small className="permissionHint">{readOnly ? "로그인하면 열 수 있습니다" : "운영 권한 없음"}</small>}
                </div>
                <div className="projectRuntimeCell">
                  <span className="cellLabel">실행</span>
                  <strong className="projectRuntimeValue">{formatProjectRuntime(project)}</strong>
                  <div className="projectRuntimeMeta">
                    <span>{formatProjectMemory(project)}</span>
                    {primaryLink ? (
                      <a href={primaryLink.url} target="_blank" rel="noreferrer">
                        {primaryLink.service ? `${primaryLink.service} 바로가기` : "서비스 바로가기"}
                      </a>
                    ) : (
                      <span>프론트 URL 없음</span>
                    )}
                    {publicLinks.length > 1 && <span>URL +{publicLinks.length - 1}</span>}
                  </div>
                </div>
                <div className="projectMetaCell">
                  <div>
                    <span className="cellLabel">최근 배포</span>
                    <strong>{formatRelativeDate(project.last_deployed_at)}</strong>
                  </div>
                  <div>
                    <span className="cellLabel">기술스택</span>
                    <span>{projectStackText(project)}</span>
                  </div>
                </div>
                <button
                  className="projectOpenButton"
                  onClick={() => onSelect(project.name)}
                  disabled={locked}
                  aria-label={locked ? `${project.name} 프로젝트는 로그인 또는 운영 권한이 필요합니다.` : `${project.name} 프로젝트 열기`}
                >
                  {readOnly ? "로그인 후 열기" : locked ? "권한 없음" : "열기"}
                </button>
              </article>
            );
          })}
          {!error && projects.length === 0 && <p className="hint">표시할 프로젝트가 없습니다. 새 프로젝트를 만들거나 로그인 상태를 확인하세요.</p>}
        </div>
      )}
    </section>
  );
}

function ProjectListSkeleton() {
  return (
    <div className="projectIndex skeletonIndex" role="status" aria-label="프로젝트 목록을 불러오는 중입니다">
      {[0, 1].map((item) => (
        <div className="projectRow skeletonRow" key={item}>
          <div className="skeletonBlock short" />
          <div className="skeletonBlock medium" />
          <div className="skeletonBlock medium" />
          <div className="skeletonBlock button" />
        </div>
      ))}
    </div>
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
  onRefresh: (force?: boolean) => Promise<void>;
}) {
  const [quickPrompt, setQuickPrompt] = useState<QuickPrompt | null>(null);
  const [runtimeServices, setRuntimeServices] = useState<Record<string, ServiceRuntime>>({});
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState("");
  const [actionBusy, setActionBusy] = useState<string>("");
  const [actionOutput, setActionOutput] = useState<ServiceActionOutput | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingServiceAction | null>(null);
  const services = projectServiceNames(project);
  const runtimeList = Object.values(runtimeServices);
  const summary = projectRuntimeSummary(runtimeList, project);

  async function refreshRuntime(force = false) {
    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      const data = await api<{ result?: { services?: ServiceRuntime[] } }>(`/api/projects/${project.name}/execute`, auth, {
        method: "POST",
        headers: force ? { "Cache-Control": "no-cache" } : undefined,
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
    await Promise.all([onRefresh(true), refreshRuntime(true)]);
  }

  function requestServiceAction(service: string, action: ServiceAction) {
    if (requiresServiceConfirmation(action)) {
      setActionOutput(null);
      setPendingAction({ service, action });
      return;
    }
    void runServiceAction(service, action);
  }

  async function confirmServiceAction() {
    if (!pendingAction) return;
    const action = pendingAction;
    setPendingAction(null);
    await runServiceAction(action.service, action.action);
  }

  async function runServiceAction(service: string, action: ServiceAction) {
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
        text: `${serviceActionLabel(action)} 요청을 실행했고 상태를 다시 확인했습니다.`,
          tone: "ok"
        });
        await Promise.all([onRefresh(true), refreshRuntime(true)]);
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
    <section className="detailPage">
      <div className="projectHero">
        <div className="projectHeroMain">
          <button className="textButton" onClick={onBack}>← 프로젝트</button>
          <h2>{project.name}</h2>
          <ProjectCapacity summary={summary} loading={runtimeLoading} />
        </div>
        <div className="headerActions">
          <button onClick={() => setQuickPrompt(makeQuickPrompt("새 서비스 배포하고 싶어"))}>새 서비스 배포</button>
          <button className="secondaryButton" onClick={onBack}>프로젝트 목록</button>
          <button className="secondaryButton" onClick={refreshWorkspace} disabled={runtimeLoading}>{runtimeLoading ? "확인 중..." : "새로고침"}</button>
        </div>
      </div>
      {runtimeError && <div className="error compactError">{runtimeError}</div>}

      <div className="projectDetailLayout">
        <main className="operationsPanel" aria-busy={runtimeLoading}>
          <div className="panelHeader">
            <div>
              <h3>서비스</h3>
              <p>상태, 프론트 URL, 리소스와 시작/중지/재시작/재배포를 확인합니다.</p>
            </div>
            <span className="panelMeta">{services.length}개 서비스</span>
          </div>
          {pendingAction ? (
            <ServiceActionConfirm
              pending={pendingAction}
              busy={Boolean(actionBusy)}
              onApprove={confirmServiceAction}
              onCancel={() => setPendingAction(null)}
            />
          ) : null}
          {actionOutput ? <ActionOutput output={actionOutput} onClose={() => setActionOutput(null)} /> : null}
          {services.length > 0 ? (
            <div className="serviceTableWrap">
              <table className="serviceTable">
                <thead>
                  <tr>
                    <th>서비스</th>
                    <th>상태</th>
                    <th>프론트 URL</th>
                    <th>포트</th>
                    <th>메모리</th>
                    <th>운영</th>
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
                      onAction={(action) => requestServiceAction(service, action)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="emptyState">
              <strong>아직 등록된 서비스가 없습니다.</strong>
              <p>GitHub 저장소와 프레임워크를 입력하면 배포 전 검증과 실행 계획을 먼저 확인할 수 있습니다.</p>
              <button onClick={() => setQuickPrompt(makeQuickPrompt("새 서비스 배포하고 싶어"))}>첫 서비스 배포 설정</button>
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
  return configured.length > 0 ? configured.join(", ") : "내부 통신";
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
  return (runtime?.container?.ports || []).find((port) => port.host)?.host || runtime?.host_port;
}

function publicUrl(runtime?: ServiceRuntime) {
  if (!runtime?.frontend) return "";
  const hostPort = firstHostPort(runtime);
  if (!hostPort) return "";
  return `${window.location.protocol}//${window.location.hostname}:${hostPort}`;
}

function projectRuntimeSummary(services: ServiceRuntime[], project?: Project) {
  const hasRuntime = services.length > 0;
  const running = hasRuntime
    ? services.filter((item) => item.container?.status === "running").length
    : project?.running_count ?? 0;
  const total = hasRuntime
    ? services.length
    : project?.service_count ?? (project ? projectServiceNames(project).length : 0);
  const runtimeMemoryValues = services
    .map((item) => item.container?.memory?.usage_mb)
    .filter((value): value is number => typeof value === "number");
  const summaryMemoryValues = (project?.service_summaries || [])
    .map((item) => item.memory_mb)
    .filter((value): value is number => typeof value === "number");
  const memory = runtimeMemoryValues.length > 0
    ? runtimeMemoryValues.reduce((sum, value) => sum + value, 0)
    : summaryMemoryValues.length > 0
      ? summaryMemoryValues.reduce((sum, value) => sum + value, 0)
      : typeof project?.memory_total_mb === "number"
        ? project.memory_total_mb
        : null;
  const projectPublicCount = project ? projectPublicLinks(project).length : 0;
  const runtimePublicCount = hasRuntime ? services.filter((item) => publicUrl(item)).length : 0;
  const publicCount = runtimePublicCount > 0 ? runtimePublicCount : projectPublicCount;
  return {
    running,
    total,
    memory: memory === null ? null : Math.round(memory * 10) / 10,
    publicCount
  };
}

function formatCapacityMemory(value: number | null, loading: boolean) {
  if (value === null) return loading ? "확인 중" : "확인 전";
  if (value >= 1024) {
    const gb = value / 1024;
    return `${gb >= 10 ? gb.toFixed(0) : gb.toFixed(1)}GB`;
  }
  return `${value % 1 ? value.toFixed(1) : value.toFixed(0)}MB`;
}

function formatCapacityPublicCount(value: number, loading: boolean) {
  if (loading && value === 0) return "확인 중";
  return value > 0 ? `${value}개` : "없음";
}

function statusLabel(status?: string, health?: string | null) {
  if (!status) return "확인 전";
  const statusLabels: Record<string, string> = {
    created: "생성됨",
    restarting: "재시작 중",
    running: "실행 중",
    removing: "삭제 중",
    paused: "일시 중지됨",
    exited: "중지됨",
    dead: "오류",
    loading: "확인 중",
    unknown: "확인 전"
  };
  const healthLabels: Record<string, string> = {
    healthy: "정상",
    unhealthy: "확인 필요",
    starting: "시작 중"
  };
  const label = statusLabels[status] || status;
  return health ? `${label} · ${healthLabels[health] || health}` : label;
}

function serviceActionLabel(action: ServiceAction | string) {
  const labels: Record<string, string> = {
    logs: "로그 조회",
    start: "시작",
    stop: "중지",
    restart: "재시작",
    redeploy: "재배포"
  };
  return labels[action] || action;
}

function requiresServiceConfirmation(action: ServiceAction): action is PendingServiceAction["action"] {
  return action === "stop" || action === "restart" || action === "redeploy";
}

function serviceActionImpact(action: PendingServiceAction["action"]) {
  const impacts: Record<PendingServiceAction["action"], string> = {
    stop: "서비스 컨테이너를 중지합니다. 외부 URL이나 내부 연결이 즉시 끊길 수 있습니다.",
    restart: "서비스 컨테이너를 다시 시작합니다. 짧은 중단이 발생할 수 있습니다.",
    redeploy: "현재 소스와 컨테이너를 새 배포 결과로 교체합니다. 검증 실패 시 복구 흐름이 필요합니다."
  };
  return impacts[action];
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
        <strong>{loading ? "확인 중" : `${summary.running}/${summary.total} 실행 중`}</strong>
      </div>
      <div>
        <span>메모리</span>
        <strong>{formatCapacityMemory(summary.memory, loading)}</strong>
      </div>
      <div>
        <span>외부 URL</span>
        <strong>{formatCapacityPublicCount(summary.publicCount, loading)}</strong>
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

function ServiceActionConfirm({
  pending,
  busy,
  onApprove,
  onCancel
}: {
  pending: PendingServiceAction;
  busy: boolean;
  onApprove: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="serviceConfirm" role="region" aria-label={`${pending.service} ${serviceActionLabel(pending.action)} 확인`}>
      <div>
        <span className="approvalStatus">승인 필요</span>
        <strong>{pending.service} {serviceActionLabel(pending.action)} 전 확인</strong>
        <p>{serviceActionImpact(pending.action)}</p>
      </div>
      <dl>
        <div>
          <dt>대상</dt>
          <dd>{pending.service}</dd>
        </div>
        <div>
          <dt>작업</dt>
          <dd>{serviceActionLabel(pending.action)}</dd>
        </div>
      </dl>
      <div className="approvalActions">
        <button className="dangerButton solidDanger" onClick={onApprove} disabled={busy}>
          {busy ? "실행 중..." : "승인하고 실행"}
        </button>
        <button className="secondaryButton" onClick={onCancel} disabled={busy}>
          취소
        </button>
      </div>
    </div>
  );
}

function serviceKind(runtime?: ServiceRuntime) {
  if (!runtime) return "확인 전";
  return runtime.frontend ? "공개 서비스" : "내부 서비스";
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
  onAction: (action: ServiceAction) => void;
}) {
  const container = runtime?.container;
  const status = container?.status || (loading ? "loading" : "unknown");
  const isRunning = status === "running";
  const url = publicUrl(runtime);
  return (
    <tr>
      <td data-label="서비스">
        <div className="serviceIdentity">
          <strong>{service}</strong>
          <span>{serviceKind(runtime)}</span>
        </div>
      </td>
      <td data-label="상태">
        <span className={`pill ${serviceStatusTone(status)}`}>{statusLabel(status, container?.health)}</span>
      </td>
      <td data-label="프론트 URL">
        {url ? (
          <a className="serviceUrl" href={url} target="_blank" rel="noreferrer">바로가기</a>
        ) : (
          <span className="mutedUrl">{runtime?.frontend ? "공개 URL 없음" : "내부 통신"}</span>
        )}
      </td>
      <td data-label="포트">{formatPort(runtime)}</td>
      <td data-label="메모리">{formatMemory(container?.memory)}</td>
      <td data-label="운영">
        <div className="serviceActions compactActions">
          <div className="primaryActions" aria-label="서비스 주요 운영 작업">
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
          <div className="secondaryActions" aria-label="서비스 로그 조회">
            <button onClick={() => onAction("logs")} disabled={Boolean(busyAction)}>
              {busyAction === "logs" ? "조회 중" : "로그"}
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}

function AgentTitleBar({
  scope,
  icon: Icon,
  scopeLabel,
  title,
  subtitle,
  statusLabel
}: {
  scope: AgentScope;
  icon: LucideIcon;
  scopeLabel: string;
  title: string;
  subtitle: string;
  statusLabel: string;
}) {
  return (
    <div className="agentTitle">
      <div className="agentTitleMain">
        <span className={`agentTitleIcon ${scope}`} aria-hidden="true">
          <Icon size={18} strokeWidth={2.2} />
        </span>
        <div>
          <span className="agentScope">{scopeLabel}</span>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </div>
      <span className="pill agentStatusPill">
        <ShieldCheck size={14} aria-hidden="true" />
        {statusLabel}
      </span>
    </div>
  );
}

function AgentActionGrid({
  actions,
  busy,
  onSelect
}: {
  actions: AgentSuggestion[];
  busy: boolean;
  onSelect: (action: AgentSuggestion) => void;
}) {
  return (
    <div className="agentActionGrid" aria-label="AI 빠른 작업">
      {actions.map((action) => {
        const Icon = action.icon;
        return (
          <button
            key={action.label}
            type="button"
            className={action.tone === "primary" ? "agentActionCard primary" : "agentActionCard"}
            onClick={() => onSelect(action)}
            disabled={busy}
          >
            <span className="agentActionIcon" aria-hidden="true">
              <Icon size={17} strokeWidth={2.2} />
            </span>
            <span>
              <strong>{action.label}</strong>
              {action.description ? <small>{action.description}</small> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function AgentEmptyState({
  icon: Icon,
  title,
  description,
  groups,
  busy,
  onSelect
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  groups: AgentSuggestionGroup[];
  busy: boolean;
  onSelect: (action: AgentSuggestion) => void;
}) {
  return (
    <div className="emptyChat">
      <div className="emptyChatHeader">
        <span className="emptyChatMark" aria-hidden="true">
          <Icon size={20} strokeWidth={2.2} />
        </span>
        <div>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
      </div>
      <div className="promptGroups">
        {groups.map((group) => (
          <div className="promptGroup" key={group.title}>
            <span>{group.title}</span>
            <div>
              {group.prompts.map((prompt) => {
                const PromptIcon = prompt.icon;
                return (
                  <button
                    key={prompt.label}
                    type="button"
                    onClick={() => onSelect(prompt)}
                    disabled={busy}
                    title={prompt.description}
                  >
                    <PromptIcon size={15} aria-hidden="true" />
                    {prompt.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentComposer({
  input,
  onInput,
  onSend,
  placeholder,
  ariaLabel,
  busy
}: {
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  placeholder: string;
  ariaLabel: string;
  busy: boolean;
}) {
  return (
    <div className="agentComposer">
      <Search className="composerSearchIcon" size={17} aria-hidden="true" />
      <input
        value={input}
        onChange={(event) => onInput(event.target.value)}
        onKeyDown={(event) => event.key === "Enter" && onSend()}
        placeholder={placeholder}
        aria-label={ariaLabel}
        disabled={busy}
      />
      <button className="composerSendButton" onClick={onSend} disabled={busy || !input.trim()} aria-label="메시지 보내기">
        {busy ? <Loader2 size={17} aria-hidden="true" /> : <Send size={17} aria-hidden="true" />}
      </button>
    </div>
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
  const deployGuideRef = useRef<HTMLDivElement | null>(null);
  const approvalCardRef = useRef<HTMLDivElement | null>(null);
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
    requestAnimationFrame(() => {
      const latestMessage = messages[messages.length - 1];
      if (latestMessage?.approval) {
        approvalCardRef.current?.scrollIntoView({ behavior: "auto", block: "start" });
        return;
      }
      if (showDeployGuide) {
        deployGuideRef.current?.scrollIntoView({ behavior: "auto", block: "start" });
        return;
      }
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }, [messages, busy, showDeployGuide]);

  const primaryService = services[0];
  const actionCards: AgentSuggestion[] = [
    {
      label: "배포 요청서",
      description: "repo와 프레임워크를 검증한 뒤 승인 단계로 이동",
      text: "새 서비스 배포하고 싶어",
      icon: Rocket,
      form: true,
      tone: "primary"
    },
    {
      label: "상태 요약",
      description: "실행 중인 서비스와 확인 필요한 항목 정리",
      text: "서비스 목록 보여줘",
      icon: Activity
    },
    {
      label: "운영 확인",
      description: "재시작·재배포 전 영향과 체크리스트 확인",
      text: primaryService ? `${primaryService} 재시작 전에 영향과 확인할 점을 알려줘` : "서비스 운영 기준을 알려줘",
      icon: ClipboardCheck
    }
  ];
  const promptGroups: AgentSuggestionGroup[] = [
    {
      title: "상태 확인",
      prompts: [
        { label: "서비스 요약", text: "서비스 목록 보여줘", icon: ListChecks },
        { label: "문제 찾기", text: "실행 중인 서비스 중 확인이 필요한 항목을 알려줘", icon: Activity }
      ]
    },
    {
      title: "배포",
      prompts: [
        { label: "배포 요청서", text: "새 서비스 배포하고 싶어", icon: Rocket, form: true },
        { label: "프레임워크 도움", text: "지원하는 프레임워크와 각각 언제 쓰는지 알려줘", icon: HelpCircle }
      ]
    },
    {
      title: "운영",
      prompts: primaryService
        ? [
            { label: "재시작 전 확인", text: `${primaryService} 재시작 전에 영향과 확인할 점을 알려줘`, icon: RotateCcw },
            { label: "로그 확인", text: `${primaryService} 로그를 확인하고 핵심만 요약해줘`, icon: FileText }
          ]
        : [
            { label: "필요 정보", text: "첫 서비스 배포에 필요한 정보를 알려줘", icon: MessageSquareText },
            { label: "운영 기준", text: "서비스 배포 후 확인해야 할 운영 기준을 알려줘", icon: ClipboardCheck }
          ]
    }
  ];

  function handleAgentAction(action: AgentSuggestion) {
    if (action.form) {
      setShowDeployGuide(true);
      setInput("");
      return;
    }
    void sendText(action.text);
  }

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
        body: JSON.stringify({ message: text, context })
      });
      if (data.context && typeof data.context === "object") {
        setContext(data.context as Record<string, unknown>);
      }
      if (isApprovalAgentResponse(data)) {
        if (data.skill === "service.deploy") {
          setShowDeployGuide(false);
          setDeployGuideErrors({});
        }
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
      { from: "agent", text: String(data.message || "새 서비스 배포는 아래 입력 카드에서 진행합니다.") }
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
    const frameworkText = deployGuide.framework === "auto"
      ? "프레임워크는 저장소 구조를 검증해서 자동 감지해줘."
      : `프레임워크는 ${selectedFramework?.label || deployGuide.framework} (${deployGuide.framework}).`;
    const text = [
      `${project} 프로젝트에 새 서비스를 배포하고 싶어.`,
      `서비스 이름은 ${deployGuide.service}.`,
      `GitHub 저장소는 ${deployGuide.repoUrl}.`,
      frameworkText,
      deployGuide.isWeb === "web"
        ? "브라우저에서 접속하는 웹서비스야. 프론트엔드면 바로가기 URL도 보여줘."
        : "외부 URL이 필요 없는 내부 서비스야.",
      ...optionalParts,
      "이 정보로 배포 전 검증을 먼저 해줘. 잘못된 정보가 있으면 잘못된 필드만 다시 확인하고, 검증이 통과하면 실행 계획을 보여준 다음 최종 승인받아 진행해줘."
    ].join(" ");
    await sendText(text, "배포 요청서 검증 요청");
  }

  const deployGuideReady = Boolean(
    deployGuide.service.trim()
    && deployGuide.repoUrl.trim()
    && GITHUB_REPO_URL_PATTERN.test(deployGuide.repoUrl.trim())
    && deployGuide.framework
    && (deployGuide.useDefaults || !deployGuide.hostPort.trim() || /^\d{2,5}$/.test(deployGuide.hostPort.trim()))
  );

  return (
    <section className="agentPanel projectAgentPanel">
      <AgentTitleBar
        scope="project"
        icon={Bot}
        scopeLabel={`${project} 프로젝트`}
        title="운영 AI"
        subtitle="배포 요청서 · 상태 해석 · 실행 전 승인"
        statusLabel="승인 후 실행"
      />
      <AgentActionGrid actions={actionCards} busy={busy} onSelect={handleAgentAction} />
      <div className="messages">
        {messages.length === 0 && (
          <AgentEmptyState
            icon={Sparkles}
            title="필요한 작업을 고르세요"
            description="배포는 요청서로 정보를 모으고, 상태 변경은 최종 승인 전까지 실행하지 않습니다."
            groups={promptGroups}
            busy={busy}
            onSelect={handleAgentAction}
          />
        )}
        {messages.map((message, index) => (
          <div className={`bubble ${message.from}`} key={index}>
            <MessageText text={message.text} />
            {message.approval ? (
              <ApprovalCard
                containerRef={approvalCardRef}
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
            containerRef={deployGuideRef}
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
            <Loader2 className="spinnerIcon" size={17} aria-hidden="true" />
            <p>요청을 검토하는 중입니다...</p>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <AgentComposer
        input={input}
        onInput={setInput}
        onSend={send}
        placeholder={`${project} 안에서 상태 확인이나 운영 질문 입력`}
        ariaLabel="프로젝트 도우미에게 보낼 메시지"
        busy={busy}
      />
    </section>
  );
}

function DeployGuideCard({
  containerRef,
  busy,
  deployGuide,
  errors,
  deployGuideReady,
  onChange,
  onSubmit
}: {
  containerRef?: React.Ref<HTMLDivElement>;
  busy: boolean;
  deployGuide: DeployGuideState;
  errors: Record<string, string>;
  deployGuideReady: boolean;
  onChange: (patch: Partial<DeployGuideState>) => void;
  onSubmit: () => void;
}) {
  const repoUrlLooksValid = !deployGuide.repoUrl.trim()
    || GITHUB_REPO_URL_PATTERN.test(deployGuide.repoUrl.trim());
  const repoUrlError = errors.repo_url || (!repoUrlLooksValid ? "https://github.com/<owner>/<repo> 형식의 공개 저장소 URL을 입력하세요." : "");
  const hostPortLooksValid = deployGuide.useDefaults || !deployGuide.hostPort.trim() || /^\d{2,5}$/.test(deployGuide.hostPort.trim());
  const hostPortError = errors.host_port || (!hostPortLooksValid ? "포트는 2~5자리 숫자로 입력하세요." : "");
  const selectedFramework = frameworkOptions.find((item) => item.id === deployGuide.framework);
  const envNames = deployGuide.envNames
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const fieldErrors = {
    ...errors,
    ...(repoUrlError ? { repo_url: repoUrlError } : {}),
    ...(hostPortError ? { host_port: hostPortError } : {})
  };
  const errorEntries = Object.entries(fieldErrors).filter(([, message]) => Boolean(message));
  const stage = busy ? "validating" : errorEntries.length > 0 ? "needsCorrection" : deployGuideReady ? "review" : "collect";
  const stages = [
    { id: "collect", label: "정보 입력" },
    { id: "validating", label: "검증" },
    { id: "review", label: "계획 확인" },
    { id: "approval", label: "최종 승인" }
  ];
  const activeStageIndex = stage === "needsCorrection"
    ? 0
    : stage === "validating"
      ? 1
      : stage === "review"
        ? 2
        : 0;
  const submitLabel = busy
    ? "검증 중..."
    : errorEntries.length > 0
      ? "수정 내용 다시 검증"
      : deployGuideReady
        ? "검증 요청"
        : "필수 정보 입력 필요";

  return (
    <div className="guidedDeploy chatGuidedDeploy" ref={containerRef}>
      <div className="guidedHeader">
        <div>
          <p className="formKicker">배포 요청서</p>
          <strong>필수 정보를 먼저 검증합니다</strong>
          <p>잘못된 값이 있으면 해당 항목만 다시 확인하고, 검증 통과 후 최종 승인을 받습니다.</p>
        </div>
        <span className={`pill requestStage ${stage}`}>{stage === "needsCorrection" ? "수정 필요" : stage === "review" ? "계획 확인" : stage === "validating" ? "검증 중" : "작성 중"}</span>
      </div>
      <div className="requestStepper" aria-label="배포 요청 단계">
        {stages.map((item, index) => (
          <div className={index <= activeStageIndex ? "active" : ""} key={item.id}>
            <span>{index + 1}</span>
            <strong>{item.label}</strong>
          </div>
        ))}
      </div>
      {errorEntries.length > 0 ? (
        <div className="formIssueSummary" role="alert">
          <strong>다시 확인할 항목</strong>
          <ul>
            {errorEntries.map(([field, message]) => (
              <li key={field}><b>{deployFieldLabel(field)}</b> {message}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className={errors.service ? "questionBlock errorField" : "questionBlock"}>
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
      <div className={repoUrlError ? "questionBlock errorField" : "questionBlock"}>
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
      <div className={errors.framework ? "questionBlock errorField" : "questionBlock"}>
        <span>프레임워크를 어떻게 확인할까요? <em>필수</em></span>
        <small>확실하지 않으면 자동 감지를 선택하세요. AI가 저장소 구조를 검증한 뒤 계획을 제안합니다.</small>
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
          <label className={hostPortError ? "questionBlock errorField" : "questionBlock"}>
            <span>호스트 포트</span>
            <small>비워두면 9000~9100 범위에서 자동 추천합니다.</small>
            <input
              value={deployGuide.hostPort}
              onChange={(event) => onChange({ hostPort: event.target.value })}
              placeholder="비우면 9000~9100 자동 추천"
              disabled={busy}
            />
            {hostPortError ? <small className="fieldError">{hostPortError}</small> : null}
          </label>
          <label className={errors.environment_names ? "questionBlock errorField" : "questionBlock"}>
            <span>환경변수 이름</span>
            <small>실제 비밀값은 요청에 포함하지 않습니다. 이름만 쉼표로 적어주세요.</small>
            <input
              value={deployGuide.envNames}
              onChange={(event) => onChange({ envNames: event.target.value })}
              placeholder="예: DATABASE_URL, API_KEY"
              disabled={busy}
            />
            {errors.environment_names ? <small className="fieldError">{errors.environment_names}</small> : null}
          </label>
        </div>
      ) : null}
      <div className="requestSummary">
        <div>
          <strong>작성 내용</strong>
          <p>검증 요청 전 입력값을 확인하세요. 실제 실행은 다음 승인 카드에서 한 번 더 확인합니다.</p>
        </div>
        <dl>
          <div>
            <dt>서비스</dt>
            <dd>{deployGuide.service.trim() || "입력 필요"}</dd>
          </div>
          <div>
            <dt>저장소</dt>
            <dd>{deployGuide.repoUrl.trim() || "입력 필요"}</dd>
          </div>
          <div>
            <dt>프레임워크</dt>
            <dd>{selectedFramework?.label || "선택 필요"}</dd>
          </div>
          <div>
            <dt>접속</dt>
            <dd>{deployGuide.isWeb === "web" ? "웹 바로가기 필요" : "내부 서비스"}</dd>
          </div>
          <div>
            <dt>포트</dt>
            <dd>{deployGuide.useDefaults ? "자동 추천" : deployGuide.hostPort.trim() || "자동 추천"}</dd>
          </div>
          <div>
            <dt>환경변수</dt>
            <dd>{envNames.length > 0 ? envNames.join(", ") : "이름 없음"}</dd>
          </div>
        </dl>
      </div>
      <div className="guidedFooter">
        <p>{deployGuideReady ? "검증을 요청하면 AI가 저장소와 입력값을 확인하고 실행 계획 또는 수정 항목을 돌려줍니다." : "서비스 이름, GitHub URL, 프레임워크 확인 방식을 먼저 채워주세요."}</p>
        <button onClick={onSubmit} disabled={busy || !deployGuideReady}>
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

function approvalStatusLabel(status: ApprovalRequest["status"]) {
  const labels: Record<ApprovalRequest["status"], string> = {
    pending: "승인 대기",
    executing: "실행 중",
    done: "완료",
    failed: "실패 또는 취소"
  };
  return labels[status];
}

function ApprovalCard({
  containerRef,
  approval,
  onApprove,
  onCancel,
  busy
}: {
  containerRef?: React.Ref<HTMLDivElement>;
  approval: ApprovalRequest;
  onApprove: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const args = approval.arguments;
  const preview = isRecord(approval.preview) ? approval.preview : {};
  const command = String(preview.command || preview.action || labelSkill(approval.skill));
  const steps = previewSteps(approval.preview);
  const checks = previewStringList(approval.preview, "checks");
  const impact = previewStringList(approval.preview, "impact");
  const disabled = busy || approval.status !== "pending";
  const isDeployApproval = approval.skill === "service.deploy";

  return (
    <div className={isDeployApproval ? "approvalCard deployApproval" : "approvalCard"} ref={containerRef}>
      <div className="approvalHeader">
        <div>
          <span className="approvalKicker">{isDeployApproval ? "최종 승인" : "실행 승인"}</span>
          <strong>{labelSkill(approval.skill)}</strong>
        </div>
        <span className={`approvalStatus ${approval.status}`}>{approvalStatusLabel(approval.status)}</span>
      </div>
      {isDeployApproval ? (
        <div className="approvalNotice">
          <strong>아직 배포는 실행되지 않았습니다.</strong>
          <p>아래 대상과 실행 예정 단계를 확인한 뒤 승인하면 실제 작업을 시작합니다.</p>
        </div>
      ) : null}
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
      {checks.length > 0 || impact.length > 0 ? (
        <div className="approvalReviewGrid">
          {checks.length > 0 ? (
            <div>
              <strong>검증 결과</strong>
              <ul>
                {checks.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          ) : null}
          {impact.length > 0 ? (
            <div>
              <strong>영향</strong>
              <ul>
                {impact.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
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
          {approval.status === "executing" ? "실행 중..." : isDeployApproval ? "승인하고 배포" : "승인하고 실행"}
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
  const [context, setContext] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const approvalCardRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const actionCards: AgentSuggestion[] = [
    {
      label: "서버 상태 점검",
      description: "디스크, 메모리, swap, 컨테이너 상태 확인",
      text: "서버 상태 확인해줘",
      icon: ServerCog,
      tone: "primary"
    },
    {
      label: "프로젝트 요약",
      description: "전체 프로젝트와 실행 중인 서비스 정리",
      text: "전체 프로젝트와 실행 중인 서비스를 요약해줘",
      icon: ListChecks
    },
    {
      label: "느림 원인 확인",
      description: "디스크와 swap 기준으로 병목 확인",
      text: "서버가 느린 이유를 디스크와 swap 기준으로 점검해줘",
      icon: Activity
    }
  ];
  const promptGroups: AgentSuggestionGroup[] = [
    {
      title: "전체 점검",
      prompts: [
        { label: "서버 상태", text: "서버 상태 확인해줘", icon: ServerCog },
        { label: "확인 필요 컨테이너", text: "재시작 중이거나 unhealthy인 컨테이너가 있는지 찾아줘", icon: ShieldCheck }
      ]
    },
    {
      title: "프로젝트 관리",
      prompts: [
        { label: "프로젝트 목록", text: "전체 프로젝트 목록 보여줘", icon: ListChecks },
        { label: "프로젝트 생성 준비", text: "새 프로젝트 생성하려면 필요한 정보를 알려줘", icon: ClipboardCheck }
      ]
    },
    {
      title: "운영 진단",
      prompts: [
        { label: "디스크/swap", text: "디스크와 swap 상태를 보고 느려질 수 있는 원인을 알려줘", icon: Activity },
        { label: "운영 기준", text: "이 서버에서 프로젝트를 운영할 때 우선 확인해야 할 기준을 알려줘", icon: MessageSquareText }
      ]
    }
  ];

  useEffect(() => {
    requestAnimationFrame(() => {
      const latestMessage = messages[messages.length - 1];
      if (latestMessage?.approval) {
        approvalCardRef.current?.scrollIntoView({ behavior: "auto", block: "start" });
        return;
      }
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }, [messages, busy]);

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
      const data = await api<Record<string, unknown>>("/api/admin/execute", auth, {
        method: "POST",
        body: JSON.stringify({
          skill: approval.skill,
          arguments: approval.arguments,
          approved: true,
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
      const data = await api<AgentResponse>("/api/admin/chat", auth, {
        method: "POST",
        body: JSON.stringify({ message: text, context })
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

  function handleAgentAction(action: AgentSuggestion) {
    void sendText(action.text);
  }

  return (
    <section className="workspace admin">
      <div className="workspaceHeader">
        <div>
          <h2>루트 AI 에이전트</h2>
        </div>
      </div>
      <div className="agentPanel rootAgentPanel">
        <AgentTitleBar
          scope="root"
          icon={ServerCog}
          scopeLabel="루트 범위"
          title="서버 운영 AI"
          subtitle="전체 상태 점검 · 프로젝트 요약 · 루트 작업 승인"
          statusLabel="Admin 전용"
        />
        <AgentActionGrid actions={actionCards} busy={busy} onSelect={handleAgentAction} />
        <div className="messages">
          {messages.length === 0 && (
            <AgentEmptyState
              icon={Sparkles}
              title="전체 서버에서 무엇을 확인할까요?"
              description="루트 AI는 서버와 모든 프로젝트를 볼 수 있습니다. 변경 작업은 승인 전까지 실행하지 않습니다."
              groups={promptGroups}
              busy={busy}
              onSelect={handleAgentAction}
            />
          )}
          {messages.map((message, index) => (
            <div className={`bubble ${message.from}`} key={index}>
              <MessageText text={message.text} />
              {message.approval ? (
                <ApprovalCard
                  containerRef={approvalCardRef}
                  approval={message.approval}
                  onApprove={() => approve(index, message.approval!)}
                  onCancel={() => updateApproval(index, "failed")}
                  busy={busy}
                />
              ) : null}
            </div>
          ))}
          {busy && (
            <div className="bubble agent loadingBubble">
              <Loader2 className="spinnerIcon" size={17} aria-hidden="true" />
              <p>루트 범위에서 요청을 검토하는 중입니다...</p>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        <AgentComposer
          input={input}
          onInput={setInput}
          onSend={send}
          placeholder="전체 서버 상태나 프로젝트 운영 질문 입력"
          ariaLabel="루트 AI 에이전트에게 보낼 명령"
          busy={busy}
        />
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
