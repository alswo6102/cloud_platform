export type Role = "visitor" | "user" | "admin";

export type Page =
  | { kind: "home" }
  | { kind: "project"; project: string }
  | { kind: "deploy"; project: string };

export type Scope = "all" | "mine";

export type AuthSession = {
  id: string;
  role: Role;
  name?: string;
  token: string;
} | null;

export type AuthHeaders = {
  role: Role;
  userId: string;
  token: string;
};

export type ProjectPublicUrl = {
  service?: string;
  host_port?: number | string | null;
};

export type ProjectServiceSummary = {
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

export type Project = {
  name: string;
  owner?: string | null;
  services?: string[];
  service_summaries?: ProjectServiceSummary[];
  frameworks?: string[];
  running_count?: number;
  service_count?: number;
  attention_count?: number;
  memory_total_mb?: number;
  public_urls?: ProjectPublicUrl[];
  last_deployed_at?: string | null;
  runtime_error?: string | boolean | null;
};

export type IncompleteProject = {
  name: string;
  reason?: string;
};

export type RuntimePort = {
  host?: number | string;
  container?: number | string;
};

export type RuntimeMemory = {
  usage_mb?: number;
  limit_mb?: number | null;
  percent?: number | null;
};

export type RuntimeContainer = {
  name?: string;
  status?: string;
  health?: string | null;
  restart_count?: number;
  ports?: RuntimePort[];
  memory?: RuntimeMemory | null;
};

export type ServiceRuntime = {
  service: string;
  configured_ports?: string[];
  frontend?: boolean;
  host_port?: number | string | null;
  container?: RuntimeContainer | null;
};

export type SystemSummary = {
  docker?: boolean;
  containers?: number;
  running?: number;
  disk_percent?: number;
  disk_free_mb?: number;
  memory_percent?: number;
  memory_total_mb?: number;
  memory_available_mb?: number;
  swap_used_mb?: number;
  swap_percent?: number;
  performance_warnings?: string[];
  unhealthy?: string[];
  restarting?: string[];
};

export type FrameworkPreset = {
  id: string;
  label: string;
  category?: string;
  description?: string;
  environment?: string[];
};

/** The four container states the console renders differently. */
export type ServiceState = "running" | "restarting" | "exited" | "unknown";

export type ServiceAction =
  | "logs"
  | "start"
  | "stop"
  | "restart"
  | "redeploy"
  | "ports"
  | "delete";

export type FieldContract = {
  name?: string;
  field?: string;
  label?: string;
  question?: string;
  type?: string;
  rules?: string;
  examples?: string[];
  required?: boolean;
};

export type UiHint = {
  type?: string;
  form?: string;
  title?: string;
  required?: string[];
  optional?: string[];
  arguments?: Record<string, unknown>;
  missing?: FieldContract[];
  field_errors?: Record<string, string>;
  choices?: Record<string, unknown>;
};

export type AgentResponse = {
  message?: string;
  mode?: string;
  kind?: string;
  skill?: string;
  model?: string;
  result?: unknown;
  context?: Record<string, unknown>;
  requires_approval?: boolean;
  arguments?: Record<string, unknown>;
  preview?: unknown;
  resume?: unknown;
  missing?: FieldContract[];
  ui?: UiHint | null;
  /** Read-only skills the planner ran to build this reply, in order. */
  tools?: Array<{ skill: string; arguments?: Record<string, unknown>; result?: unknown }>;
  field_errors?: Record<string, string>;
  error?: unknown;
};

export type ToolCall = {
  skill: string;
  summary: string;
  evidence: string[];
};

export type ApprovalPlan = {
  skill: string;
  arguments: Record<string, unknown>;
  preview?: unknown;
  resume?: unknown;
  status: "pending" | "executing" | "done" | "failed";
};

export type AgentMessage = {
  id: number;
  from: "user" | "agent";
  text: string;
  tools?: ToolCall[];
  approval?: ApprovalPlan;
  /** A question the agent asked for one missing deploy field. */
  question?: FieldContract;
  /** Fields already answered, shown as collapsed confirmations. */
  answered?: Array<{ label: string; value: string }>;
  tone?: "normal" | "error";
};

export type AgentScope = { kind: "project"; name: string } | { kind: "root" };

export type PanelMode = "rail" | "wide" | "full";
