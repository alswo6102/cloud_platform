import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Role = "visitor" | "user" | "admin";

type Project = {
  name: string;
  services?: string[];
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
  result?: unknown;
  missing?: unknown[];
};

const headers = (role: Role) => ({
  "Content-Type": "application/json",
  "X-User-Role": role,
  "X-User-Id": "local-user"
});

async function api<T>(path: string, role: Role, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...headers(role),
      ...(init?.headers || {})
    }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
  const lines = [
    `${labelSkill(data.skill)} 실행 전 확인이 필요합니다.`,
    `대상: ${project}${service}`,
    "필요한 정보가 확인됐습니다. 아래 내용을 검토한 뒤 승인하면 작업을 시작합니다."
  ];
  return lines.join("\n");
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

function App() {
  const [role, setRole] = useState<Role>("user");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const selected = useMemo(
    () => projects.find((project) => project.name === selectedProject),
    [projects, selectedProject]
  );

  async function refreshProjects() {
    if (role === "visitor") {
      setProjects([]);
      setSelectedProject("");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api<{ projects: Project[] }>("/api/projects", role);
      setProjects(data.projects || []);
      setSelectedProject((current) => current || data.projects?.[0]?.name || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshProjects();
  }, [role]);

  return (
    <main className="shell">
      <header className="hero">
        <div className="heroCopy">
          <p className="eyebrow">Cloud Platform Console</p>
          <h1>프로젝트별로 분리되는 배포 콘솔</h1>
          <p>
            프로젝트를 만들고, 각 프로젝트 workspace 안에서 서비스 배포·상태·로그를
            AI 에이전트와 검증된 실행 도구를 통해 안전하게 처리합니다.
          </p>
          <div className="heroBadges" aria-label="console architecture summary">
            <span>Project namespace</span>
            <span>Guarded actions</span>
            <span>Approval before changes</span>
          </div>
        </div>
        <label className="rolePicker">
          <span>개발용 권한</span>
          <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
            <option value="visitor">비유저</option>
            <option value="user">일반 유저</option>
            <option value="admin">어드민</option>
          </select>
        </label>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="grid">
        <LandingCard role={role} onCreated={refreshProjects} />
        <ProjectList
          role={role}
          projects={projects}
          selectedProject={selectedProject}
          loading={loading}
          onSelect={setSelectedProject}
        />
      </section>

      {selected && (
        <ProjectWorkspace
          role={role}
          project={selected}
          onRefresh={refreshProjects}
        />
      )}

      {role === "admin" && <AdminConsole role={role} />}
    </main>
  );
}

function LandingCard({
  role,
  onCreated
}: {
  role: Role;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<unknown | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function createProject(approved: boolean) {
    setBusy(true);
    setMessage("");
    try {
      const data = await api<unknown>("/api/projects", role, {
        method: "POST",
        body: JSON.stringify({ name, approved })
      });
      if (!approved) {
        setPreview(data);
        setMessage("생성 전 미리보기입니다. 확인 후 승인하세요.");
      } else {
        setPreview(null);
        setName("");
        setMessage("프로젝트를 생성했습니다.");
        await onCreated();
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="cardTitle">
        <span className="iconBox">＋</span>
        <div>
          <h2>새 프로젝트</h2>
          <p>프로젝트 생성은 명시적인 API로 처리하고, 생성 후 상세 화면에서 AI를 사용합니다.</p>
        </div>
      </div>
      <div className="row">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
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
      {role === "visitor" && <p className="hint">비유저는 AI와 프로젝트 생성 기능을 사용할 수 없습니다.</p>}
      {message && <p className="hint">{message}</p>}
      {preview !== null && (
        <div className="previewCard">
          <strong>생성 전 확인</strong>
          <p><code>{name}</code> 프로젝트를 생성할 준비가 됐습니다. 승인하면 프로젝트 namespace와 기본 구성이 만들어집니다.</p>
        </div>
      )}
    </section>
  );
}

function ProjectList({
  role,
  projects,
  selectedProject,
  loading,
  onSelect
}: {
  role: Role;
  projects: Project[];
  selectedProject: string;
  loading: boolean;
  onSelect: (name: string) => void;
}) {
  return (
    <section className="card">
      <div className="cardTitle">
        <span className="iconBox">⌘</span>
        <div>
          <h2>내 프로젝트</h2>
          <p>현재는 로그인 전 단계라 개발용 헤더 권한으로 표시합니다.</p>
        </div>
      </div>
      {loading && <p className="hint">불러오는 중...</p>}
      {role === "visitor" && <p className="hint">로그인 후 프로젝트 목록이 표시됩니다.</p>}
      <div className="projectList">
        {projects.map((project) => (
          <button
            key={project.name}
            className={project.name === selectedProject ? "active" : ""}
            onClick={() => onSelect(project.name)}
          >
            <strong>{project.name}</strong>
            <span>{project.services?.length || 0} services</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ProjectWorkspace({
  role,
  project,
  onRefresh
}: {
  role: Role;
  project: Project;
  onRefresh: () => Promise<void>;
}) {
  const [quickPrompt, setQuickPrompt] = useState("");
  const services = project.services || [];

  return (
    <section className="workspace">
      <div className="workspaceHeader">
        <div>
          <p className="eyebrow">Project namespace</p>
          <h2>{project.name}</h2>
          <p>이 workspace의 에이전트는 기본적으로 <code>{project.name}</code> 프로젝트만 context로 받습니다.</p>
        </div>
        <button onClick={onRefresh}>새로고침</button>
      </div>
      <div className="namespaceStats">
        <div>
          <strong>{services.length}</strong>
          <span>services</span>
        </div>
        <div>
          <strong>scoped</strong>
          <span>agent context</span>
        </div>
        <div>
          <strong>검증</strong>
          <span>safe execution</span>
        </div>
      </div>
      <div className="serviceGrid">
        {services.map((service) => (
          <div className="service" key={service}>
            <div className="serviceTop">
              <strong>{service}</strong>
              <span className="pill">managed</span>
            </div>
            <span>상태/로그/재배포는 프로젝트 에이전트가 안전하게 확인해 처리합니다.</span>
            <div className="serviceActions">
              <button onClick={() => setQuickPrompt(`${service} 상태 확인해줘`)}>상태</button>
              <button onClick={() => setQuickPrompt(`${service} 로그 40줄 보여줘`)}>로그</button>
              <button onClick={() => setQuickPrompt(`${service} 재배포하고 싶어`)}>재배포</button>
            </div>
          </div>
        ))}
        {services.length === 0 && (
          <p className="hint">아직 등록된 서비스가 없습니다.</p>
        )}
      </div>
      <AgentPanel role={role} project={project.name} quickPrompt={quickPrompt} />
    </section>
  );
}

function AgentPanel({
  role,
  project,
  quickPrompt
}: {
  role: Role;
  project: string;
  quickPrompt?: string;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId] = useState(() => crypto.randomUUID());
  const [context, setContext] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (quickPrompt) {
      setInput(quickPrompt);
    }
  }, [quickPrompt]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
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
      const data = await api<Record<string, unknown>>(`/api/projects/${project}/execute`, role, {
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
      setMessages((items) => [
        ...items,
        {
          from: "agent",
          text: summarizeExecution(data),
          }
      ]);
    } catch (err) {
      updateApproval(index, "failed");
      setMessages((items) => [
        ...items,
        {
          from: "agent",
          text: err instanceof Error ? err.message : String(err)
        }
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!input.trim()) return;
    const text = input.trim();
    setInput("");
    setMessages((items) => [...items, { from: "user", text }]);
    setBusy(true);
    try {
      const data = await api<AgentResponse>(`/api/projects/${project}/chat`, role, {
        method: "POST",
        body: JSON.stringify({ message: text, session_id: sessionId, context })
      });
      if (data.context && typeof data.context === "object") {
        setContext(data.context as Record<string, unknown>);
      }
      if (data.requires_approval && data.skill && data.arguments) {
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
      setMessages((items) => [
        ...items,
        {
          from: "agent",
          text: String(data.message || "응답을 받았습니다."),
        }
      ]);
    } catch (err) {
      setMessages((items) => [
        ...items,
        { from: "agent", text: err instanceof Error ? err.message : String(err) }
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="agent">
      <div className="agentTitle">
        <div>
          <h3>프로젝트 AI 에이전트</h3>
          <p>애매한 요청은 바로 실행하지 않고 필요한 정보를 다시 묻습니다.</p>
        </div>
        <span className="pill">session scoped</span>
      </div>
      <div className="messages">
        {messages.length === 0 && (
          <div className="emptyChat">
            예: “서비스 목록 보여줘”, “demo-a 상태 확인해줘”, “새 프론트 서비스를 배포하고 싶어”
          </div>
        )}
        {messages.map((message, index) => (
          <div className={`bubble ${message.from}`} key={index}>
            <p>{message.text}</p>
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
        {busy && (
          <div className="bubble agent loadingBubble">
            <span className="spinner" />
            <p>AI가 응답 중입니다...</p>
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

function AdminConsole({ role }: { role: Role }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId] = useState(() => crypto.randomUUID());

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    setMessages((items) => [...items, { from: "user", text }]);
    try {
      const data = await api<Record<string, unknown>>("/api/admin/chat", role, {
        method: "POST",
        body: JSON.stringify({ message: text, session_id: sessionId })
      });
      setMessages((items) => [
        ...items,
        { from: "agent", text: String(data.message || "응답을 받았습니다.") }
      ]);
    } catch (err) {
      setMessages((items) => [
        ...items,
        { from: "agent", text: err instanceof Error ? err.message : String(err) }
      ]);
    }
  }

  return (
    <section className="workspace admin">
      <div className="workspaceHeader">
        <div>
          <p className="eyebrow">Admin plane</p>
          <h2>루트 AI 에이전트</h2>
          <p>어드민만 접근하는 전체 프로젝트 관리용 에이전트 영역입니다.</p>
        </div>
      </div>
      <div className="agent">
        <div className="messages">
          {messages.map((message, index) => (
            <div className={`bubble ${message.from}`} key={index}>
              <p>{message.text}</p>
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
