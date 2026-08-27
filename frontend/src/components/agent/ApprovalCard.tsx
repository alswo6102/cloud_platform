import type { ApprovalPlan, SystemSummary } from "../../types";
import { isRecord } from "../../lib/api";
import { DASH, formatMb, skillAction, skillLabel } from "../../lib/format";
import "./ApprovalCard.css";

const DOCKERFILE_LABELS: Record<string, string> = {
  "use repository Dockerfile": "저장소의 Dockerfile 사용"
};

/** `regenerate the <framework> preset Dockerfile` — the name varies. */
function dockerfileLabel(value: string) {
  if (DOCKERFILE_LABELS[value]) return DOCKERFILE_LABELS[value];
  const preset = value.match(/^regenerate the (.+) preset Dockerfile$/);
  return preset ? `${preset[1]} 프리셋 Dockerfile 재생성` : value;
}

const STEP_LABELS: Record<string, string> = {
  "clone the latest default branch into a temporary directory": "최신 코드를 임시 공간에 내려받기",
  "validate the new root-level Dockerfile": "Dockerfile 검증",
  "atomically swap the service source directory": "소스 교체",
  "build a new image and force-recreate only the target service": "이미지 빌드 · 컨테이너 교체",
  "verify the new container stays running": "실행 확인",
  "restore the previous source and container if verification fails": "실패 시 이전 상태로 복구"
};

/** Redeploy replaces a running container; stop takes a service down. */
function isDestructive(plan: ApprovalPlan) {
  if (plan.skill === "service.redeploy" || plan.skill === "port.manage") return true;
  if (plan.skill === "service.delete") return true;
  if (plan.skill === "service.control") {
    const action = String(plan.arguments.action || "");
    return action === "stop" || action === "restart";
  }
  return false;
}

/**
 * A delete is the one plan whose cost is not that it interrupts something. The
 * dry run says so in `irreversible`; the card has to say it louder than the
 * kicker every other destructive plan shares.
 */
function isIrreversible(plan: ApprovalPlan) {
  return isRecord(plan.preview) && plan.preview.irreversible === true;
}

function previewList(preview: unknown, key: string): string[] {
  if (!isRecord(preview) || !Array.isArray(preview[key])) return [];
  return (preview[key] as unknown[]).filter((item): item is string => typeof item === "string");
}

function approvalTitle(plan: ApprovalPlan) {
  const service = plan.arguments.service ? String(plan.arguments.service) : "";
  const project = plan.arguments.project ? String(plan.arguments.project) : "";
  const subject = service || project;
  const action = skillAction(plan.skill, plan.arguments);
  return subject ? `${subject} ${action}` : skillLabel(plan.skill);
}

const STATUS_LABEL: Record<ApprovalPlan["status"], string> = {
  pending: "승인 대기",
  executing: "실행 중",
  done: "완료",
  failed: "취소됨"
};

export function ApprovalCard({
  plan,
  summary,
  result,
  onApprove,
  onCancel
}: {
  plan: ApprovalPlan;
  summary: SystemSummary | null;
  result?: string;
  onApprove: () => void;
  onCancel: () => void;
}) {
  const destructive = isDestructive(plan);
  const irreversible = isIrreversible(plan);
  const removes = previewList(plan.preview, "removes");
  const steps = previewList(plan.preview, "steps").map((step) => STEP_LABELS[step] || step);
  const impact = previewList(plan.preview, "impact");
  const checks = previewList(plan.preview, "checks");
  // A redeploy is asked for with nothing but a service name; the repository,
  // framework, and Dockerfile decision come back from the dry run. Read the
  // plan first and fall back to what the request carried.
  const preview = isRecord(plan.preview) ? plan.preview : {};
  const field = (key: string) => {
    const value = plan.arguments[key] ?? preview[key];
    return value === undefined || value === null || value === "" ? "" : String(value);
  };
  const repoUrl = field("repo_url");
  const project = field("project");
  const service = field("service");
  const framework = field("framework");
  const dockerfile = field("dockerfile");
  const hostPort = plan.arguments.host_port ?? preview.host_port;
  // A port change is the mapping it replaces; the new number alone hides that.
  const before = field("before");
  const after = field("after");
  const diskFree = formatMb(summary?.disk_free_mb);
  const disabled = plan.status !== "pending";
  const releasedPorts = Array.isArray(preview.released_host_ports)
    ? (preview.released_host_ports as unknown[]).map(String).filter(Boolean)
    : [];
  const warning = typeof preview.warning === "string" ? preview.warning : "";

  return (
    <div className={destructive ? "approval approval--destructive" : "approval"}>
      <div className="approval__head">
        <span className="approval__kicker">
          {irreversible ? "복구 불가 · 승인 필요" : destructive ? "파괴적 · 승인 필요" : "변경 · 승인 필요"}
        </span>
        <span className="approval__status">{STATUS_LABEL[plan.status]}</span>
      </div>

      <div className="approval__body">
        <div className="approval__title">{approvalTitle(plan)}</div>

        <div className="approval__spec">
          <div className="approval__specKey">대상</div>
          <div className="approval__specValue truncate" title={`${project}${service ? ` / ${service}` : ""}`}>
            {project || DASH}
            {service ? ` / ${service}` : ""}
          </div>

          {repoUrl && (
            <>
              <div className="approval__specKey">저장소</div>
              <div className="approval__specValue approval__specValue--mono">
                {repoUrl.replace(/^https?:\/\//, "")}
              </div>
            </>
          )}

          {framework && (
            <>
              <div className="approval__specKey">런타임</div>
              <div className="approval__specValue">{framework}</div>
            </>
          )}

          {before && after ? (
            <>
              <div className="approval__specKey">포트</div>
              <div className="approval__specValue approval__specValue--mono">
                {before} → {after}
              </div>
            </>
          ) : (
            hostPort != null &&
            hostPort !== "" && (
              <>
                <div className="approval__specKey">포트</div>
                <div className="approval__specValue approval__specValue--mono">
                  {String(hostPort)}
                </div>
              </>
            )
          )}

          {dockerfile && (
            <>
              <div className="approval__specKey">빌드</div>
              <div className="approval__specValue">{dockerfileLabel(dockerfile)}</div>
            </>
          )}

          {releasedPorts.length > 0 && (
            <>
              <div className="approval__specKey">회수</div>
              <div className="approval__specValue approval__specValue--mono">
                {releasedPorts.join(", ")}
              </div>
            </>
          )}
        </div>

        {removes.length > 0 && (
          <>
            <div className="approval__rule" />
            <div className="approval__colTitle approval__colTitle--risk">삭제되는 항목</div>
            <ul className="approval__removes">
              {removes.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}

        {warning && <div className="approval__warning">{warning}</div>}

        {(impact.length > 0 || steps.length > 0) && (
          <>
            <div className="approval__rule" />
            <div className="approval__grid">
              {impact.length > 0 && (
                <div>
                  <div className="approval__colTitle approval__colTitle--risk">위험</div>
                  <div className="approval__colBody">
                    {impact.map((item) => (
                      <div key={item}>{item}</div>
                    ))}
                  </div>
                </div>
              )}
              {steps.length > 0 && (
                <div>
                  <div className="approval__colTitle">예상 결과</div>
                  <div className="approval__colBody">{steps.join(" → ")}</div>
                </div>
              )}
            </div>
          </>
        )}

        {checks.length > 0 && (
          <div className="approval__colBody approval__checks">
            <div className="approval__colTitle">검증 결과</div>
            {checks.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </div>
        )}

        {result ? (
          <div className="approval__result">{result}</div>
        ) : (
          <div className="approval__actions">
            <button
              className={destructive ? "btn btn--dangerSolid" : "btn btn--primary"}
              onClick={onApprove}
              disabled={disabled}
            >
              {plan.status === "executing"
                ? "실행 중..."
                : `승인하고 ${skillAction(plan.skill, plan.arguments)}`}
            </button>
            <button className="btn" onClick={onCancel} disabled={disabled}>
              취소
            </button>
            {diskFree && <span className="approval__context">디스크 여유 {diskFree}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
