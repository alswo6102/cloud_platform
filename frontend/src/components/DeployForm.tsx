import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import type {
  AuthHeaders,
  FieldContract,
  FrameworkPreset,
  Project,
  SystemSummary
} from "../types";
import { api, errorText, isRecord } from "../lib/api";
import { DASH, formatMb, nextFreePort } from "../lib/format";
import { Field, FieldError } from "./Modal";
import "./DeployForm.css";

const NAME_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const REPO_PATTERN = /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+?(?:\.git)?\/?$/;
const ENV_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * The agent's steps are English and finer-grained than the summary needs.
 * Several map to one line on purpose: the list is deduplicated after mapping,
 * which collapses them into the three phases a reader cares about.
 */
const STEP_LABELS: Record<string, string> = {
  "clone the public GitHub repository": "저장소 클론 및 구조 검증",
  "use the repository root Dockerfile": "저장소 클론 및 구조 검증",
  "generate the selected framework Dockerfile in the server clone": "compose 생성 · 이미지 빌드",
  "add the service to the project app-net namespace": "compose 생성 · 이미지 빌드",
  "build and start only the new service": "컨테이너 실행 · 헬스 확인",
  "verify the container stays running and publishes the requested port":
    "컨테이너 실행 · 헬스 확인",
  "verify the internal-only container stays running on the app network":
    "컨테이너 실행 · 헬스 확인"
};

const CATEGORY_ORDER = ["Backend", "Frontend", "Fullstack", "Custom"];

function groupFrameworks(frameworks: FrameworkPreset[]) {
  const groups = new Map<string, FrameworkPreset[]>();
  for (const item of frameworks) {
    const key = item.category || "기타";
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups.entries()].sort(
    (a, b) =>
      (CATEGORY_ORDER.indexOf(a[0]) + 1 || 99) - (CATEGORY_ORDER.indexOf(b[0]) + 1 || 99)
  );
}

function previewStrings(preview: unknown, key: string): string[] {
  if (!isRecord(preview) || !Array.isArray(preview[key])) return [];
  return (preview[key] as unknown[]).filter((item): item is string => typeof item === "string");
}

/**
 * The direct path — no conversation needed. The plan on the right is a real dry
 * run from the agent, and pressing 배포 실행 is the approval for exactly that
 * plan; the button is dead until the plan has come back.
 */
export function DeployForm({
  auth,
  project,
  projects,
  summary,
  frameworks,
  onCancel,
  onDeployed
}: {
  auth: AuthHeaders;
  project: string;
  projects: Project[];
  summary: SystemSummary | null;
  frameworks: FrameworkPreset[];
  onCancel: () => void;
  onDeployed: () => void;
}) {
  const [service, setService] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [repoTouched, setRepoTouched] = useState(false);
  const [framework, setFramework] = useState("");
  const [isWeb, setIsWeb] = useState(true);
  const [hostPort, setHostPort] = useState("");
  const [portTouched, setPortTouched] = useState(false);
  const [envNames, setEnvNames] = useState<string[]>([]);
  const [envDraft, setEnvDraft] = useState("");

  const [preview, setPreview] = useState<unknown>(null);
  // A dry run can come back asking for a field the form does not have — an
  // `existing` image whose Dockerfile declares no EXPOSE has to be told which
  // port it listens on. That answer is not a plan, so it must not arm the
  // submit button.
  const [question, setQuestion] = useState<FieldContract | null>(null);
  const [questionNote, setQuestionNote] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [deploying, setDeploying] = useState(false);

  // The suggestion has to wait for the project list, or it recommends a port
  // something is already published on.
  useEffect(() => {
    if (portTouched || !projects.length) return;
    setHostPort(String(nextFreePort(projects)));
  }, [projects, portTouched]);

  const groups = useMemo(() => groupFrameworks(frameworks), [frameworks]);
  const selected = frameworks.find((item) => item.id === framework);
  const serviceValid = NAME_PATTERN.test(service.trim());
  const repoValid = REPO_PATTERN.test(repoUrl.trim());
  const portValid = !isWeb || /^\d{4,5}$/.test(hostPort.trim());
  const ready = serviceValid && repoValid && Boolean(framework) && portValid;

  const answered = useMemo(() => {
    const extra: Record<string, unknown> = {};
    for (const [field, value] of Object.entries(answers)) {
      const trimmed = value.trim();
      if (!trimmed) continue;
      extra[field] = /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed;
    }
    return extra;
  }, [answers]);

  const args = useMemo(
    () => ({
      service: service.trim(),
      repo_url: repoUrl.trim(),
      framework,
      is_web: isWeb,
      ...(isWeb && hostPort.trim() ? { host_port: Number(hostPort.trim()) } : {}),
      ...(envNames.length ? { environment_names: envNames } : {}),
      ...answered
    }),
    [service, repoUrl, framework, isWeb, hostPort, envNames, answered]
  );

  // The plan follows the form. Change anything and it is fetched again, so the
  // summary can never describe a deploy other than the one about to run.
  useEffect(() => {
    if (!ready) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewing(true);
    setError("");
    setFieldErrors({});
    const timer = window.setTimeout(async () => {
      try {
        const data = await api<Record<string, unknown>>(
          `/api/projects/${project}/preview`,
          auth,
          { method: "POST", body: JSON.stringify({ skill: "service.deploy", arguments: args }) }
        );
        if (cancelled) return;
        const plan = isRecord(data.preview) ? data.preview : data;
        const missing = Array.isArray(plan.needs_input) ? (plan.needs_input as FieldContract[]) : [];
        if (plan.status === "needs_input" && missing.length) {
          setPreview(null);
          setQuestion(missing[0]);
          setQuestionNote(typeof plan.message === "string" ? plan.message : "");
          return;
        }
        setQuestion(null);
        setQuestionNote("");
        setPreview(plan);
      } catch (err) {
        if (cancelled) return;
        setPreview(null);
        setQuestion(null);
        setError(errorText(err));
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [args, auth, project, ready]);

  async function deploy() {
    if (!preview || deploying) return;
    setDeploying(true);
    setError("");
    try {
      await api(`/api/projects/${project}/execute`, auth, {
        method: "POST",
        body: JSON.stringify({ skill: "service.deploy", arguments: args, approved: true })
      });
      onDeployed();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setDeploying(false);
    }
  }

  function addEnvName(raw: string) {
    const name = raw.trim().replace(/,$/, "");
    if (!name) return;
    if (!ENV_NAME_PATTERN.test(name)) {
      setFieldErrors((current) => ({
        ...current,
        environment_names: "영문자와 밑줄로 시작하는 이름만 가능합니다."
      }));
      return;
    }
    setFieldErrors((current) => {
      const next = { ...current };
      delete next.environment_names;
      return next;
    });
    setEnvNames((current) => (current.includes(name) ? current : [...current, name]));
    setEnvDraft("");
  }

  const steps = previewStrings(preview, "steps").map((step) => STEP_LABELS[step] || step);
  const uniqueSteps = [...new Set(steps)];
  const containerPort = isRecord(preview) ? preview.container_port : null;
  const resolvedHostPort = isRecord(preview) ? preview.host_port : null;
  const diskFree = formatMb(summary?.disk_free_mb);
  const diskLow = (summary?.performance_warnings || []).includes("disk_low");

  return (
    <div className="deployPage">
      <div>
        <div className="deployPage__head">
          <h1 className="deployPage__title">새 서비스 배포</h1>
          <button className="btn btn--quiet" onClick={onCancel} type="button">
            취소
          </button>
        </div>

        <div className="deployCard">
          <div className="deployGrid">
            <div>
              <Field
                label="서비스 이름"
                value={service}
                onChange={setService}
                mono
                placeholder="horse_api"
                valid={serviceValid}
                help="프로젝트 안에서만 구분됩니다"
              />
            </div>
            <div>
              <Field
                label="GitHub 저장소"
                value={repoUrl}
                onChange={(value) => {
                  setRepoUrl(value);
                  setRepoTouched(false);
                }}
                onBlur={() => setRepoTouched(true)}
                mono
                placeholder="https://github.com/owner/repo"
                valid={repoValid}
                invalid={repoTouched && Boolean(repoUrl.trim()) && !repoValid}
                help={repoValid ? "공개 저장소 형식 확인됨" : "공개 HTTPS 저장소만 배포할 수 있습니다"}
                helpTone={repoValid ? "ok" : "muted"}
              />
            </div>
          </div>

          <div className="deployRule" />

          <div className="deployLabelRow">
            <label>프레임워크</label>
            {selected && <span className="suggestPill">{selected.label} 선택됨</span>}
          </div>
          <div className="frameworkGroups">
            {groups.map(([category, items]) => (
              <div className="frameworkGroup" key={category}>
                <div className="frameworkGroup__label">{category}</div>
                <div className="frameworkGroup__chips">
                  {items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={item.id === framework ? "fwChip is-active" : "fwChip"}
                      onClick={() => setFramework(item.id)}
                      title={item.description}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="deployRule" />

          <div className="deployGrid">
            <div>
              <span className="field__label">외부 접속</span>
              <div className="segmentedTall" role="group" aria-label="외부 접속">
                <button
                  type="button"
                  className={isWeb ? "is-active" : ""}
                  onClick={() => setIsWeb(true)}
                >
                  웹 공개
                </button>
                <button
                  type="button"
                  className={!isWeb ? "is-active" : ""}
                  onClick={() => setIsWeb(false)}
                >
                  내부 전용
                </button>
              </div>
            </div>
            {isWeb && (
              <div>
                <span className="field__label">호스트 포트</span>
                <div className="portControl">
                  <input
                    className="portControl__input"
                    value={hostPort}
                    onChange={(event) => {
                      setPortTouched(true);
                      setHostPort(event.target.value);
                    }}
                    inputMode="numeric"
                    aria-label="호스트 포트"
                  />
                  <span className="portControl__hint">자동 추천 · 9000–9100</span>
                </div>
                {!portValid && <FieldError>9000–9100 범위의 포트를 입력하세요.</FieldError>}
              </div>
            )}
          </div>

          <div className="deployRule" />

          <div>
            <span className="field__label">환경변수 이름</span>
            <div className="envBox">
              {envNames.map((name) => (
                <span className="envChip" key={name}>
                  {name}
                  <button
                    type="button"
                    className="envChip__remove"
                    onClick={() => setEnvNames((current) => current.filter((item) => item !== name))}
                    aria-label={`${name} 제거`}
                  >
                    <X size={10} aria-hidden="true" />
                  </button>
                </span>
              ))}
              <input
                className="envBox__input"
                value={envDraft}
                onChange={(event) => setEnvDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === ",") {
                    event.preventDefault();
                    addEnvName(envDraft);
                  }
                }}
                onBlur={() => addEnvName(envDraft)}
                placeholder={envNames.length ? "이름 추가" : "DATABASE_URL"}
                aria-label="환경변수 이름 추가"
              />
            </div>
            {fieldErrors.environment_names ? (
              <FieldError>{fieldErrors.environment_names}</FieldError>
            ) : (
              <div className="field__help">
                이름만 compose에 등록됩니다. 요청에 비밀값을 담지 않습니다.
              </div>
            )}
          </div>
        </div>
      </div>

      <div>
        <div className="planCard">
          <div className="planCard__label">실행 계획</div>
          <div className="planCard__spec">
            <div className="planCard__key">서비스</div>
            <div className="planCard__value planCard__value--strong truncate">
              {service.trim() || DASH}
            </div>
            <div className="planCard__key">런타임</div>
            <div className="planCard__value truncate">{selected?.label || DASH}</div>
            <div className="planCard__key">포트</div>
            <div className="planCard__value planCard__value--mono">
              {isWeb
                ? resolvedHostPort && containerPort
                  ? `${resolvedHostPort}→${containerPort}`
                  : hostPort.trim() || DASH
                : containerPort
                  ? String(containerPort)
                  : DASH}
            </div>
            <div className="planCard__key">공개</div>
            <div className="planCard__value">{isWeb ? "웹 공개" : "없음 (내부 전용)"}</div>
          </div>

          <div className="planCard__rule" />

          {question ? (
            <div className="planQuestion">
              <div className="planQuestion__label">{question.label || "추가 정보"}</div>
              {questionNote && <div className="planQuestion__note">{questionNote}</div>}
              <div className="planQuestion__ask">{question.question}</div>
              <div className="portControl">
                <input
                  className="portControl__input"
                  value={answers[question.field || question.name || ""] || ""}
                  onChange={(event) =>
                    setAnswers((current) => ({
                      ...current,
                      [question.field || question.name || ""]: event.target.value
                    }))
                  }
                  inputMode={question.type === "integer" ? "numeric" : "text"}
                  placeholder={question.examples?.[0] != null ? String(question.examples[0]) : ""}
                  aria-label={question.label || "추가 정보"}
                />
              </div>
            </div>
          ) : (
            <>
              <div className="planCard__stepsLabel">진행 순서</div>
              <div className="planCard__steps">
                {uniqueSteps.length ? (
                  uniqueSteps.map((step, index) => (
                    <div key={step}>
                      {index + 1} · {step}
                    </div>
                  ))
                ) : (
                  <div>
                    {previewing
                      ? "실행 계획을 확인하는 중입니다."
                      : "필수 항목을 채우면 실행 계획을 확인합니다."}
                  </div>
                )}
              </div>
            </>
          )}

          {diskLow && diskFree && (
            <div className="planCard__warn">
              현재 디스크 여유는 {diskFree}입니다. 빌드 도중 공간이 부족할 수 있습니다.
            </div>
          )}

          {error && <FieldError>{error}</FieldError>}

          <button
            className="btn btn--primary planCard__submit"
            onClick={() => void deploy()}
            disabled={!preview || previewing || deploying}
          >
            {deploying ? "배포 중..." : "배포 실행"}
          </button>
          <div className="planCard__note">
            {question
              ? "답하면 실행 계획을 다시 확인합니다."
              : "이 계획 그대로 실행합니다. 실행 전 마지막 확인입니다."}
          </div>
        </div>
      </div>
    </div>
  );
}
