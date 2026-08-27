import { ArrowUpRight } from "lucide-react";
import type {
  IncompleteProject,
  Project,
  Role,
  Scope,
  SystemSummary
} from "../types";
import {
  DASH,
  availablePortRange,
  barWidth,
  formatMb,
  projectAttention,
  projectFrameworkLabels,
  projectPublicLinks,
  projectServiceNames
} from "../lib/format";
import { CapacityAlert, ServerStrip } from "./ServerStrip";
import { EmptyState, TableSkeleton } from "./States";
import "./ProjectIndex.css";

function StatusBadge({ level, label }: { level: "danger" | "warn"; label: string }) {
  return (
    <span className={level === "danger" ? "badge badge--danger" : "badge badge--warn"}>
      <span
        className={level === "danger" ? "badgeGlyph badgeGlyph--bar" : "badgeGlyph badgeGlyph--diamond"}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

function ProjectRow({
  project,
  incompleteReason,
  showOwner,
  memoryTotalMb,
  canOpen,
  onOpen
}: {
  project: Project;
  incompleteReason?: string;
  showOwner: boolean;
  memoryTotalMb?: number;
  canOpen: boolean;
  onOpen: () => void;
}) {
  const attention = projectAttention(project, incompleteReason);
  const services = projectServiceNames(project);
  const links = projectPublicLinks(project);
  const primaryLink = links[0];
  const stack = projectFrameworkLabels(project);
  const total = project.service_count ?? services.length;
  const running = project.running_count ?? 0;
  const memory = formatMb(project.memory_total_mb);
  const memoryPercent =
    memoryTotalMb && typeof project.memory_total_mb === "number"
      ? (project.memory_total_mb / memoryTotalMb) * 100
      : null;

  const rowClass = [
    "projectRow",
    attention.level === "danger" ? "projectRow--danger" : "",
    attention.level === "warn" ? "projectRow--warn" : ""
  ]
    .filter(Boolean)
    .join(" ");

  const subText = attention.level === "none" ? services.join(" · ") : attention.text;
  const subClass = [
    "projectRow__sub",
    attention.level === "danger" ? "projectRow__sub--danger" : "",
    attention.level === "warn" ? "projectRow__sub--warn" : ""
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rowClass} role="listitem">
      <div style={{ minWidth: 0 }}>
        <div className="projectRow__name">
          <strong className="truncate" title={project.name}>
            {project.name}
          </strong>
          {attention.badge && <StatusBadge level={attention.level as "danger" | "warn"} label={attention.badge} />}
          {attention.level === "none" && primaryLink && (
            <a
              className="projectRow__link"
              href={primaryLink.url}
              target="_blank"
              rel="noreferrer"
              title={primaryLink.url}
            >
              {primaryLink.service || "바로가기"}
              <ArrowUpRight size={12} aria-hidden="true" />
            </a>
          )}
        </div>
        <div className={subClass}>
          {canOpen ? subText || "서비스 없음" : "멤버가 아닙니다"}
        </div>
      </div>

      {showOwner && <div className="projectRow__owner truncate">{project.owner || DASH}</div>}

      <div
        className={total === 0 ? "projectRow__running projectRow__running--idle" : "projectRow__running"}
      >
        {running}/{total}
      </div>

      <div className="projectRow__memory">
        {memory ? (
          <>
            <div className="meter meter--sm" style={{ width: 56 }}>
              <i style={{ width: `${barWidth(memoryPercent)}%` }} />
            </div>
            <span className="projectRow__memoryValue">{memory}</span>
          </>
        ) : (
          <span className="cellEmpty">{DASH}</span>
        )}
      </div>

      <div className={stack.length ? "projectRow__stack truncate" : "projectRow__stack cellEmpty"}>
        {stack.length ? stack.join(" · ") : "확인 전"}
      </div>

      <div className="projectRow__action">
        <button className="btn" onClick={onOpen} disabled={!canOpen}>
          열기
        </button>
      </div>
    </div>
  );
}

export function ProjectIndex({
  role,
  scope,
  onScopeChange,
  allProjects,
  incomplete,
  memberOf,
  summary,
  loading,
  serverDetailOpen,
  onToggleServerDetail,
  onOpenProject,
  onNewProject,
  agentSlot
}: {
  role: Role;
  scope: Scope;
  onScopeChange: (scope: Scope) => void;
  allProjects: Project[];
  incomplete: IncompleteProject[];
  memberOf: Set<string>;
  summary: SystemSummary | null;
  loading: boolean;
  serverDetailOpen: boolean;
  onToggleServerDetail: () => void;
  onOpenProject: (project: string) => void;
  onNewProject: () => void;
  agentSlot?: React.ReactNode;
}) {
  // "내 프로젝트" is membership, not what you are allowed to see — otherwise an
  // admin's two filters would always show the same rows.
  const projects =
    scope === "all" ? allProjects : allProjects.filter((item) => memberOf.has(item.name));
  const isAdmin = role === "admin";
  const showOwner = isAdmin && scope === "all";
  const incompleteReasons = new Map(incomplete.map((item) => [item.name, item.reason || ""]));
  const portRange = availablePortRange(allProjects);

  return (
    <div className="pageMain">
      <div className="indexTitleRow">
        <div className="indexTitleRow__left">
          <h1 className="indexTitle">프로젝트</h1>
          <div className="segmented" role="group" aria-label="프로젝트 범위">
            <button
              className={scope === "all" ? "is-active" : ""}
              onClick={() => onScopeChange("all")}
              aria-pressed={scope === "all"}
            >
              전체 프로젝트
              <span className="segmented__count">{allProjects.length}</span>
            </button>
            <button
              className={scope === "mine" ? "is-active" : ""}
              onClick={() => onScopeChange("mine")}
              aria-pressed={scope === "mine"}
            >
              내 프로젝트
              <span className="segmented__count">
                {allProjects.filter((item) => memberOf.has(item.name)).length}
              </span>
            </button>
          </div>
        </div>
        <button className="btn btn--primary btn--md" onClick={onNewProject}>
          새 프로젝트
        </button>
      </div>

      <ServerStrip
        summary={summary}
        portRange={portRange}
        detailed={isAdmin}
        detailOpen={serverDetailOpen}
        onToggleDetail={onToggleServerDetail}
      />
      <CapacityAlert summary={summary} />

      <div
        className={showOwner ? "projectTable projectTable--admin" : "projectTable"}
        role="list"
      >
        <div className="projectTable__head" role="presentation">
          <div>프로젝트</div>
          {showOwner && <div>소유자</div>}
          <div>실행</div>
          <div>메모리</div>
          <div>스택</div>
          <div />
        </div>

        {loading && projects.length === 0 ? (
          <TableSkeleton note="Docker stats를 읽는 중입니다 · 3초 넘으면 캐시된 값을 먼저 보여줍니다" />
        ) : projects.length === 0 ? (
          <EmptyState
            title={scope === "mine" ? "아직 프로젝트가 없습니다" : "표시할 프로젝트가 없습니다"}
            body="프로젝트를 만들면 그 안에 서비스를 올릴 수 있습니다."
            action={
              <button className="btn btn--primary btn--md" onClick={onNewProject}>
                새 프로젝트
              </button>
            }
          />
        ) : (
          projects.map((project) => (
            <ProjectRow
              key={project.name}
              project={project}
              incompleteReason={incompleteReasons.get(project.name)}
              showOwner={showOwner}
              memoryTotalMb={summary?.memory_total_mb}
              canOpen={isAdmin || memberOf.has(project.name)}
              onOpen={() => onOpenProject(project.name)}
            />
          ))
        )}
      </div>

      {agentSlot}
    </div>
  );
}

/**
 * The same home, narrowed to what is public: a name, how many services are
 * reachable, and the link. No locked buttons to press and be refused.
 */
export function PublicIndex({
  projects,
  summary,
  loading,
  error,
  onRetry
}: {
  projects: Project[];
  summary: SystemSummary | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  const visible = projects
    .map((project) => ({ project, links: projectPublicLinks(project) }))
    .filter((item) => item.links.length > 0);

  return (
    <div className="pageMain">
      <div className="indexTitleRow">
        <div className="indexTitleRow__left">
          <h1 className="indexTitle">프로젝트</h1>
          <span className="scopeBadge">공개 범위</span>
        </div>
      </div>

      <ServerStrip summary={summary} />

      <div className="publicList">
        {loading && visible.length === 0 ? (
          <TableSkeleton rows={2} />
        ) : error ? (
          <EmptyState
            title="공개 목록을 불러오지 못했습니다"
            body={error}
            action={
              <button className="btn" onClick={onRetry}>
                다시 시도
              </button>
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState title="공개된 서비스가 없습니다" body="로그인하면 참여 중인 프로젝트가 보입니다." />
        ) : (
          visible.map(({ project, links }) => (
            <div className="publicRow" key={project.name}>
              <strong className="truncate" title={project.name}>
                {project.name}
              </strong>
              <span className="publicRow__count">공개 서비스 {links.length}개</span>
              <a
                className="publicRow__link"
                href={links[0].url}
                target="_blank"
                rel="noreferrer"
                title={links[0].url}
              >
                {links[0].service || "바로가기"}
                <ArrowUpRight size={12} aria-hidden="true" />
              </a>
            </div>
          ))
        )}
      </div>

      <p className="indexFootnote">
        로그인하면 참여 중인 프로젝트의 상태 확인과 운영 작업이 열립니다.
      </p>
    </div>
  );
}
