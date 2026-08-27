import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, ArrowUpRight, ChevronDown, Maximize2, Minimize2, X } from "lucide-react";
import type {
  AgentMessage,
  AgentResponse,
  AgentScope,
  ApprovalPlan,
  AuthHeaders,
  FieldContract,
  FrameworkPreset,
  PanelMode,
  SystemSummary
} from "../../types";
import { api, errorText, isRecord } from "../../lib/api";
import { skillAction, skillLabel } from "../../lib/format";
import { toolCallFrom } from "../../lib/toolCalls";
import { ErrorPanel } from "../States";
import { ApprovalCard } from "./ApprovalCard";
import { AnsweredLine, FrameworkSuggestion, QuestionHint } from "./DeployQuestion";
import { Message } from "./Message";
import "./AgentPanel.css";

export const RAIL_MIN = 420;
export const RAIL_MAX = 720;

/** A job handed to the panel from outside — a prompt, or a plan to approve. */
export type AgentRequest =
  | { nonce: number; kind: "prompt"; text: string }
  | { nonce: number; kind: "plan"; skill: string; arguments: Record<string, unknown> };

const PROJECT_SUGGESTIONS = [
  "지금 상태 요약해줘",
  "확인이 필요한 서비스를 찾아줘",
  "새 서비스 배포하고 싶어"
];

const ROOT_SUGGESTIONS = [
  "서버 상태 확인해줘",
  "전체 프로젝트를 요약해줘",
  "재시작 중이거나 응답 없는 컨테이너를 찾아줘"
];

const DEPLOY_FIELD_LABELS: Record<string, string> = {
  service: "이름",
  repo_url: "저장소",
  framework: "프레임워크",
  host_port: "포트",
  environment_names: "환경변수"
};

function isApprovalResponse(data: AgentResponse) {
  return data.requires_approval === true && typeof data.skill === "string" && isRecord(data.arguments);
}

function isDeployForm(data: AgentResponse) {
  return data.ui?.type === "form" && data.ui.form === "service.deploy";
}

function answeredEntries(args: Record<string, unknown> | undefined) {
  if (!args) return [];
  return Object.entries(args)
    .filter(([key, value]) => DEPLOY_FIELD_LABELS[key] && value !== null && value !== "" && value !== undefined)
    .map(([key, value]) => ({
      label: DEPLOY_FIELD_LABELS[key],
      value: Array.isArray(value) ? value.map(String).join(", ") : String(value)
    }));
}

function summarizeExecution(data: unknown, skill: string) {
  if (!isRecord(data)) return `${skillLabel(skill)}를 실행했습니다.`;
  const result = isRecord(data.result) ? data.result : data;
  const status = result.status || result.message || result.action;
  return status
    ? `${skillLabel(skill)}를 실행했습니다. ${String(status)}`
    : `${skillLabel(skill)}를 실행했습니다.`;
}

export function AgentPanel({
  auth,
  scope,
  summary,
  mode,
  onModeChange,
  railWidth,
  onRailWidthChange,
  onClose,
  request,
  onMutationDone,
  frameworks
}: {
  auth: AuthHeaders;
  scope: AgentScope;
  summary: SystemSummary | null;
  mode: PanelMode;
  onModeChange: (mode: PanelMode) => void;
  railWidth: number;
  onRailWidthChange: (width: number) => void;
  onClose: () => void;
  request?: AgentRequest | null;
  onMutationDone: () => void;
  frameworks: FrameworkPreset[];
}) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState("");
  const [context, setContext] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [changeCount, setChangeCount] = useState(0);
  const [streamingId, setStreamingId] = useState<number | null>(null);
  const [showAllFrameworks, setShowAllFrameworks] = useState(false);
  const [results, setResults] = useState<Record<number, string>>({});

  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const nextId = useRef(1);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const isProject = scope.kind === "project";
  const scopeName = isProject ? scope.name : "전체 서버";
  const chatPath = isProject ? `/api/projects/${scope.name}/chat` : "/api/admin/chat";
  const executePath = isProject ? `/api/projects/${scope.name}/execute` : "/api/admin/execute";
  const previewPath = isProject ? `/api/projects/${scope.name}/preview` : "/api/admin/preview";
  const suggestions = isProject ? PROJECT_SUGGESTIONS : ROOT_SUGGESTIONS;

  const lastQuestion = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].question) return messages[index];
    }
    return null;
  }, [messages]);

  const deployProgress = useMemo(() => {
    if (!lastQuestion?.answered) return null;
    const required = ["service", "repo_url", "framework"];
    const done = lastQuestion.answered.filter((entry) =>
      required.some((field) => DEPLOY_FIELD_LABELS[field] === entry.label)
    ).length;
    return `${done}/${required.length} 단계`;
  }, [lastQuestion]);

  const clearStreaming = useCallback(() => setStreamingId(null), []);

  const addMessage = useCallback((message: Omit<AgentMessage, "id">) => {
    const id = nextId.current++;
    setMessages((items) => [...items, { ...message, id }]);
    return id;
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  // ------------------------------------------------------------- sending
  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;
      setInput("");
      setFailure("");
      addMessage({ from: "user", text: trimmed });
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const data = await api<AgentResponse>(chatPath, auth, {
          method: "POST",
          body: JSON.stringify({ message: trimmed, context }),
          signal: controller.signal
        });

        if (data.context && typeof data.context === "object") {
          setContext(data.context as Record<string, unknown>);
        }

        const tool = toolCallFrom(data);
        const tools = tool ? [tool] : undefined;

        if (isApprovalResponse(data)) {
          const plan = await withPreview({
            skill: String(data.skill),
            arguments: data.arguments as Record<string, unknown>,
            preview: data.preview,
            resume: data.resume,
            status: "pending"
          });
          const id = addMessage({
            from: "agent",
            text: String(data.message || ""),
            tools,
            approval: plan
          });
          setStreamingId(id);
          return;
        }

        if (isDeployForm(data)) {
          const id = addMessage({
            from: "agent",
            text: String(data.message || ""),
            tools,
            question: data.ui?.missing?.[0],
            answered: answeredEntries(data.ui?.arguments)
          });
          setStreamingId(id);
          setShowAllFrameworks(false);
          return;
        }

        const id = addMessage({
          from: "agent",
          text: String(data.message || "응답을 받았습니다."),
          tools
        });
        setStreamingId(id);
      } catch (err) {
        if ((err as Error)?.name === "AbortError") {
          addMessage({ from: "agent", text: "요청을 중지했습니다.", tone: "error" });
          return;
        }
        setFailure(errorText(err));
      } finally {
        abortRef.current = null;
        setBusy(false);
      }
    },
    [addMessage, auth, busy, chatPath, context]
  );

  /** Ask the agent for the dry run behind a plan, so the card is not a guess. */
  const withPreview = useCallback(
    async (plan: ApprovalPlan): Promise<ApprovalPlan> => {
      if (plan.preview) return plan;
      try {
        const data = await api<Record<string, unknown>>(previewPath, auth, {
          method: "POST",
          body: JSON.stringify({ skill: plan.skill, arguments: plan.arguments })
        });
        return { ...plan, preview: isRecord(data.preview) ? data.preview : data };
      } catch {
        return plan;
      }
    },
    [auth, previewPath]
  );

  // --------------------------------------------------- outside-in requests
  const handledNonce = useRef(0);
  useEffect(() => {
    if (!request || request.nonce === handledNonce.current) return;
    handledNonce.current = request.nonce;

    if (request.kind === "prompt") {
      void send(request.text);
      return;
    }

    void (async () => {
      setFailure("");
      const plan = await withPreview({
        skill: request.skill,
        arguments: request.arguments,
        status: "pending"
      });
      const target = request.arguments.service ? `${request.arguments.service} ` : "";
      const id = addMessage({
        from: "agent",
        text: `${target}${skillAction(request.skill, request.arguments)} 전에 확인이 필요합니다. 아직 실행하지 않았습니다.`,
        approval: plan
      });
      setStreamingId(id);
    })();
  }, [request, send, withPreview, addMessage]);

  // ------------------------------------------------------------ approving
  function updatePlan(id: number, patch: Partial<ApprovalPlan>) {
    setMessages((items) =>
      items.map((item) =>
        item.id === id && item.approval ? { ...item, approval: { ...item.approval, ...patch } } : item
      )
    );
  }

  async function approve(id: number, plan: ApprovalPlan) {
    updatePlan(id, { status: "executing" });
    setBusy(true);
    setFailure("");
    try {
      const data = await api<Record<string, unknown>>(executePath, auth, {
        method: "POST",
        body: JSON.stringify({
          skill: plan.skill,
          arguments: plan.arguments,
          approved: true,
          resume: plan.resume
        })
      });
      updatePlan(id, { status: "done" });
      setResults((current) => ({ ...current, [id]: summarizeExecution(data, plan.skill) }));
      setChangeCount((count) => count + 1);
      onMutationDone();
    } catch (err) {
      updatePlan(id, { status: "failed" });
      setResults((current) => ({ ...current, [id]: errorText(err) }));
    } finally {
      setBusy(false);
    }
  }

  // ---------------------------------------------------------- rail resize
  function startResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = railWidth;
    const move = (moveEvent: PointerEvent) => {
      const next = Math.min(RAIL_MAX, Math.max(RAIL_MIN, startWidth + (startX - moveEvent.clientX)));
      onRailWidthChange(next);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  // ------------------------------------------------------- fullscreen a11y
  useEffect(() => {
    if (mode !== "full") return;
    restoreFocusRef.current = document.activeElement as HTMLElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    overlayRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onModeChange("rail");
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      restoreFocusRef.current?.focus?.();
    };
  }, [mode, onModeChange]);

  // ------------------------------------------------------------ rendering
  const frameworkById = useMemo(
    () => new Map(frameworks.map((item) => [item.id, item])),
    [frameworks]
  );

  function renderQuestion(message: AgentMessage) {
    const field = message.question;
    if (!field) return null;
    const name = field.field || field.name;

    if (name === "framework" && frameworks.length > 0) {
      const proposedId = message.answered?.find((entry) => entry.label === "프레임워크")?.value;
      const proposed = proposedId ? frameworkById.get(proposedId) : undefined;
      if (proposed) {
        return (
          <FrameworkSuggestion
            suggestion={proposed}
            alternatives={frameworks.filter((item) => item.id !== proposed.id)}
            showAll={showAllFrameworks}
            onToggleAll={() => setShowAllFrameworks(!showAllFrameworks)}
            onConfirm={() => send(`프레임워크는 ${proposed.label} (${proposed.id}) 맞아요.`)}
            onPick={(id) => send(`프레임워크는 ${frameworkById.get(id)?.label || id} (${id}).`)}
            disabled={busy}
          />
        );
      }
      const visible = showAllFrameworks ? frameworks : frameworks.slice(0, 4);
      return (
        <div className="suggestCard__alts suggestCard__alts--standalone">
          {visible.map((item) => (
            <button
              key={item.id}
              className="chip"
              onClick={() => send(`프레임워크는 ${item.label} (${item.id}).`)}
              disabled={busy}
            >
              {item.label}
            </button>
          ))}
          {frameworks.length > visible.length && (
            <button className="chip chip--plain" onClick={() => setShowAllFrameworks(true)}>
              전체 {frameworks.length}종
              <ChevronDown size={12} aria-hidden="true" />
            </button>
          )}
        </div>
      );
    }

    return <QuestionHint field={field} />;
  }

  const body = (
    <div
      className={messages.length === 0 ? "agentPanel__body agentPanel__body--empty" : "agentPanel__body"}
      aria-live="polite"
    >
      {messages.length === 0 ? (
        <div className={mode === "full" ? "agentOverlay__column" : undefined}>
          <div className="suggestLabel">시작해볼 것</div>
          <div className="suggestList">
            {suggestions.map((text) => (
              <button
                key={text}
                className="suggestItem"
                onClick={() => send(text)}
                disabled={busy}
              >
                {text}
                <ArrowUpRight size={13} aria-hidden="true" />
              </button>
            ))}
            <div className="suggestList__end" />
          </div>
        </div>
      ) : (
        <>
          {messages.map((message) => (
            <div
              className={mode === "full" ? "agentOverlay__column msgBlock" : "msgBlock"}
              key={message.id}
            >
              {message.answered && message.answered.length > 0 && (
                <div className="msgBlock__answered">
                  <AnsweredLine
                    entries={message.answered}
                    onEdit={(entry) => {
                      // Field-level correction: the server re-asks only the
                      // value that changed, so hand the composer a start.
                      setInput(`${entry.label}은 `);
                      composerRef.current?.focus();
                    }}
                  />
                </div>
              )}
              <Message
                message={message}
                streaming={streamingId === message.id}
                onStreamEnd={clearStreaming}
              >
                {message.approval && (
                  <div className="msgBlock__card">
                    <ApprovalCard
                      plan={message.approval}
                      summary={summary}
                      result={results[message.id]}
                      onApprove={() => approve(message.id, message.approval!)}
                      onCancel={() => updatePlan(message.id, { status: "failed" })}
                    />
                  </div>
                )}
                {renderQuestion(message)}
              </Message>
            </div>
          ))}

          {busy && (
            <div className={mode === "full" ? "agentOverlay__column" : undefined}>
              <div className="agentProgress">
                <span className="spinner" aria-hidden="true" />
                에이전트에 요청하는 중…
              </div>
            </div>
          )}

          {failure && (
            <div className={mode === "full" ? "agentOverlay__column" : undefined}>
              <ErrorPanel
                title="운영 AI가 응답하지 않습니다"
                body={`${failure} 서비스 상태와 조작 버튼은 정상 동작합니다.`}
                onRetry={() => {
                  const lastUser = [...messages].reverse().find((item) => item.from === "user");
                  if (lastUser) void send(lastUser.text);
                }}
                onDismiss={onClose}
                dismissLabel="AI 없이 계속"
              />
            </div>
          )}
        </>
      )}
      <div ref={endRef} />
    </div>
  );

  const composer = (
    <div className="composer">
      <div className={mode === "full" ? "agentOverlay__column" : undefined}>
        <div className="composer__box">
          <textarea
            className="composer__input"
            ref={composerRef}
            rows={1}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(input);
              }
            }}
            placeholder={
              isProject
                ? `${scopeName}에 대해 물어보기`
                : "전체 서버 상태에 대해 물어보기"
            }
            aria-label="운영 AI에게 보낼 메시지"
          />
          {busy ? (
            <button
              className="composer__send composer__send--stop"
              onClick={() => abortRef.current?.abort()}
              aria-label="응답 중지"
            >
              <i />
            </button>
          ) : (
            <button
              className={
                input.trim() ? "composer__send composer__send--ready" : "composer__send"
              }
              onClick={() => void send(input)}
              disabled={!input.trim()}
              aria-label="메시지 보내기"
            >
              <ArrowUp size={15} aria-hidden="true" />
            </button>
          )}
        </div>
        {isProject && messages.length === 0 && (
          <div className="composer__note">
            시작·중지·로그는 서비스 표에서 바로 누르는 게 빠릅니다.
          </div>
        )}
      </div>
    </div>
  );

  if (mode === "full") {
    return (
      <>
        <div className="agentBackdrop" onClick={() => onModeChange("rail")} />
        <div
          className="agentOverlay"
          role="dialog"
          aria-modal="true"
          aria-label="운영 AI"
          tabIndex={-1}
          ref={overlayRef}
        >
          <div className="agentOverlay__head">
            <span className="agentMark" aria-hidden="true">
              AI
            </span>
            <span className="agentOverlay__title">운영 AI</span>
            <span className="scopeChip">{scopeName}</span>
            <span className="changeChip">
              실행한 변경 {changeCount}건
              <ChevronDown size={12} aria-hidden="true" />
            </span>
            <button
              className="linkButton agentOverlay__shrink"
              onClick={() => onModeChange("rail")}
            >
              축소 <Minimize2 size={12} aria-hidden="true" />
            </button>
            <button className="linkButton" onClick={onClose}>
              닫기 <span className="agentOverlay__esc">ESC</span>
            </button>
          </div>
          {body}
          {composer}
        </div>
      </>
    );
  }

  return (
    <aside className="agentPanel">
      <div
        className="agentPanel__handle"
        onPointerDown={startResize}
        role="separator"
        aria-orientation="vertical"
        aria-label="AI 패널 너비 조절"
      />
      <div className="agentPanel__head">
        <span className="agentMark" aria-hidden="true">
          AI
        </span>
        <div className="agentPanel__ident">
          <div className="agentPanel__title">운영 AI</div>
          <div className="agentPanel__scope truncate">
            {scopeName} 범위 · {deployProgress || "변경은 승인 후 실행"}
          </div>
        </div>
        <div className="agentPanel__tools">
          <button
            className="iconButton"
            onClick={() => onModeChange("full")}
            aria-label="전체화면으로 열기"
          >
            <Maximize2 size={12} aria-hidden="true" />
          </button>
          <button className="iconButton" onClick={onClose} aria-label="AI 패널 닫기">
            <X size={12} aria-hidden="true" />
          </button>
        </div>
      </div>
      {body}
      {composer}
    </aside>
  );
}
