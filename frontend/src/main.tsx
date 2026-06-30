import React, { useEffect, useMemo, useState } from "react";
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
  raw?: unknown;
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
        <div>
          <p className="eyebrow">Cloud Platform Console</p>
          <h1>프로젝트 단위로 격리되는 배포 콘솔</h1>
          <p>
            메인에서는 프로젝트를 만들고, 프로젝트 상세 안에서는 해당 namespace의
            서비스만 AI 에이전트가 다룹니다.
          </p>
        </div>
        <label className="rolePicker">
          개발용 권한
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
  const [preview, setPreview] = useState<unknown>(null);
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
      <h2>새 프로젝트</h2>
      <p>
        프로젝트 생성은 AI가 아니라 명시적인 API로 처리합니다. 생성 후 프로젝트
        상세에서 AI 에이전트를 사용합니다.
      </p>
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
        <button disabled={!preview || busy || role === "visitor"} onClick={() => createProject(true)}>
          승인 생성
        </button>
      </div>
      {role === "visitor" && <p className="hint">비유저는 AI와 프로젝트 생성 기능을 사용할 수 없습니다.</p>}
      {message && <p className="hint">{message}</p>}
      {preview && <pre>{JSON.stringify(preview, null, 2)}</pre>}
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
      <h2>내 프로젝트</h2>
      <p>현재는 로그인 전 단계라 개발용 헤더 권한으로 표시합니다.</p>
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
  return (
    <section className="workspace">
      <div className="workspaceHeader">
        <div>
          <p className="eyebrow">Project namespace</p>
          <h2>{project.name}</h2>
          <p>이 화면의 AI 에이전트는 기본적으로 이 프로젝트를 context로 받습니다.</p>
        </div>
        <button onClick={onRefresh}>새로고침</button>
      </div>
      <div className="serviceGrid">
        {(project.services || []).map((service) => (
          <div className="service" key={service}>
            <strong>{service}</strong>
            <span>상태/로그/재배포는 에이전트 또는 CLI API를 통해 조회</span>
          </div>
        ))}
        {(!project.services || project.services.length === 0) && (
          <p className="hint">아직 등록된 서비스가 없습니다.</p>
        )}
      </div>
      <AgentPanel role={role} project={project.name} />
    </section>
  );
}

function AgentPanel({ role, project }: { role: Role; project: string }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId] = useState(() => crypto.randomUUID());
  const [context, setContext] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!input.trim()) return;
    const text = input.trim();
    setInput("");
    setMessages((items) => [...items, { from: "user", text }]);
    setBusy(true);
    try {
      const data = await api<Record<string, unknown>>(`/api/projects/${project}/chat`, role, {
        method: "POST",
        body: JSON.stringify({ message: text, session_id: sessionId, context })
      });
      if (data.context && typeof data.context === "object") {
        setContext(data.context as Record<string, unknown>);
      }
      setMessages((items) => [
        ...items,
        {
          from: "agent",
          text: String(data.message || "응답을 받았습니다."),
          raw: data
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
      <h3>프로젝트 AI 에이전트</h3>
      <div className="messages">
        {messages.map((message, index) => (
          <div className={`bubble ${message.from}`} key={index}>
            <p>{message.text}</p>
            {message.raw ? <details><summary>raw</summary><pre>{JSON.stringify(message.raw, null, 2)}</pre></details> : null}
          </div>
        ))}
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
        { from: "agent", text: String(data.message || "응답을 받았습니다."), raw: data }
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
              {message.raw ? <details><summary>raw</summary><pre>{JSON.stringify(message.raw, null, 2)}</pre></details> : null}
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
