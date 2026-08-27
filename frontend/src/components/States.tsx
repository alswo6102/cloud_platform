import { useEffect, useState } from "react";
import "./States.css";

/**
 * A spinner that flashes for 80ms is worse than no spinner. Loading state only
 * becomes visible once the wait is long enough to notice.
 */
export function useDelayedFlag(active: boolean, delayMs = 200) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!active) {
      setVisible(false);
      return;
    }
    const timer = window.setTimeout(() => setVisible(true), delayMs);
    return () => window.clearTimeout(timer);
  }, [active, delayMs]);
  return visible;
}

export function TableSkeleton({ rows = 3, note }: { rows?: number; note?: string }) {
  const widths = [86, 112, 74, 96];
  return (
    <div role="status" aria-label="목록을 불러오는 중입니다">
      {Array.from({ length: rows }).map((_, index) => (
        <div className="skeletonRow" key={index}>
          <div className="sk sk--strong" style={{ width: widths[index % widths.length] }} />
          <div className="sk" style={{ width: 52 }} />
          <div style={{ flex: 1 }} />
          <div className="sk sk--btn" />
        </div>
      ))}
      {note && <div className="skeletonNote">{note}</div>}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action
}: {
  title: string;
  body?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="emptyState">
      <div className="emptyState__mark" aria-hidden="true" />
      <div className="emptyState__title">{title}</div>
      {body && <div className="emptyState__body">{body}</div>}
      {action && <div className="emptyState__action">{action}</div>}
    </div>
  );
}

export function ErrorPanel({
  title,
  body,
  onRetry,
  onDismiss,
  dismissLabel = "닫기"
}: {
  title: string;
  body: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  dismissLabel?: string;
}) {
  return (
    <div className="errorPanel" role="alert">
      <div className="errorPanel__title">{title}</div>
      <div className="errorPanel__body">{body}</div>
      {(onRetry || onDismiss) && (
        <div className="errorPanel__actions">
          {onRetry && (
            <button className="btn btn--danger" onClick={onRetry}>
              다시 시도
            </button>
          )}
          {onDismiss && (
            <button className="btn btn--quiet" onClick={onDismiss}>
              {dismissLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * For actions that undo cleanly. A reversible stop does not deserve the same
 * ceremony as a redeploy — it just needs a moment to change your mind.
 */
export function InlineConfirm({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="inlineConfirm" role="alertdialog" aria-label={title}>
      <div className="inlineConfirm__text">
        <b>{title}</b>
        <span>{body}</span>
      </div>
      <button className="btn" onClick={onConfirm}>
        {confirmLabel}
      </button>
      <button className="btn btn--quiet" onClick={onCancel}>
        취소
      </button>
    </div>
  );
}

/** Says when the numbers on screen were last true, rather than implying now. */
export function StaleNotice({ checkedAt }: { checkedAt: string }) {
  return (
    <div className="staleNotice" role="status">
      <b>API 연결이 끊겼습니다.</b> 마지막 확인 {checkedAt} · 화면 값은 그때 기준입니다.
    </div>
  );
}
