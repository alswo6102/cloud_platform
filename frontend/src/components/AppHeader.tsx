import type { AuthSession, Page } from "../types";
import "./AppHeader.css";

/**
 * The path lives here, so no screen needs its own back button. Breadcrumb in,
 * breadcrumb out.
 */
export function AppHeader({
  page,
  session,
  onNavigate,
  onLogin,
  onLogout
}: {
  page: Page;
  session: AuthSession;
  onNavigate: (page: Page) => void;
  onLogin: () => void;
  onLogout: () => void;
}) {
  const project = page.kind === "home" ? null : page.project;

  return (
    <header className="appHeader">
      <div className="appHeader__left">
        <button
          className="brand"
          onClick={() => onNavigate({ kind: "home" })}
          aria-label="Cloud Platform 홈"
        >
          <span className="brand__mark" aria-hidden="true">
            <i />
          </span>
          <span className="brand__name">Cloud Platform</span>
        </button>

        {project && (
          <>
            <span className="crumbSep" aria-hidden="true">
              /
            </span>
            <button className="crumbLink" onClick={() => onNavigate({ kind: "home" })}>
              프로젝트
            </button>
            <span className="crumbSep" aria-hidden="true">
              /
            </span>
            {page.kind === "deploy" ? (
              <>
                <button
                  className="crumbLink"
                  onClick={() => onNavigate({ kind: "project", project })}
                >
                  {project}
                </button>
                <span className="crumbSep" aria-hidden="true">
                  /
                </span>
                <span className="crumbCurrent">새 서비스</span>
              </>
            ) : (
              <span className="crumbCurrent truncate" title={project}>
                {project}
              </span>
            )}
          </>
        )}
      </div>

      <div className="appHeader__right">
        {session ? (
          <>
            <div className="appHeader__user">
              <span className="appHeader__userName">{session.name || session.id}</span>
              {session.role === "admin" && <span className="roleBadge">ADMIN</span>}
            </div>
            <button className="linkButton" onClick={onLogout}>
              로그아웃
            </button>
          </>
        ) : (
          <button className="btn btn--dark" onClick={onLogin}>
            로그인
          </button>
        )}
      </div>
    </header>
  );
}
