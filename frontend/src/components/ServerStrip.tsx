import { AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import type { SystemSummary } from "../types";
import { DASH, barWidth, formatMb, formatPercent } from "../lib/format";
import "./ServerStrip.css";

const DISK_ALERT_AT = 90;

function Stat({
  name,
  percent,
  showMeter = true
}: {
  name: string;
  percent?: number | null;
  showMeter?: boolean;
}) {
  const value = formatPercent(percent);
  const danger = typeof percent === "number" && percent >= DISK_ALERT_AT;
  return (
    <div className="serverStat">
      <span className="serverStat__name">{name}</span>
      {showMeter && (
        <div className={danger ? "meter meter--danger" : "meter"} style={{ width: 88 }}>
          <i style={{ width: `${barWidth(percent)}%` }} />
        </div>
      )}
      <span
        className={danger ? "serverStat__value serverStat__value--danger" : "serverStat__value"}
      >
        {value ?? DASH}
      </span>
    </div>
  );
}

export function ServerStrip({
  summary,
  portRange,
  detailed = false,
  detailOpen,
  onToggleDetail
}: {
  summary: SystemSummary | null;
  portRange?: string | null;
  /** Admins get the expandable breakdown; everyone else gets the one line. */
  detailed?: boolean;
  detailOpen?: boolean;
  onToggleDetail?: () => void;
}) {
  const containers =
    typeof summary?.running === "number" && typeof summary?.containers === "number"
      ? `${summary.running}/${summary.containers}`
      : null;

  return (
    <div className="serverStrip">
      <div className="serverStrip__row">
        <span className="serverStrip__label">서버</span>
        {containers && (
          <div className="serverStat">
            <span className="serverStat__name">컨테이너</span>
            <span className="serverStat__value">{containers}</span>
          </div>
        )}
        <Stat name="메모리" percent={summary?.memory_percent} />
        <Stat name="디스크" percent={summary?.disk_percent} />
        {detailed ? (
          <button
            className="serverStrip__toggle"
            onClick={onToggleDetail}
            aria-expanded={detailOpen}
          >
            상세 {detailOpen ? "접기" : "펼치기"}
            {detailOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        ) : (
          portRange && (
            <div className="serverStrip__end">
              <span className="serverStat__name">가용 포트</span>
              <span className="serverStat__value">{portRange}</span>
            </div>
          )
        )}
      </div>

      {detailed && detailOpen && (
        <div className="serverStrip__detail">
          <div className="serverStrip__cell">
            <div className="serverStrip__cellLabel">디스크 여유</div>
            <div className="serverStrip__cellValue">{formatMb(summary?.disk_free_mb) ?? DASH}</div>
          </div>
          <div className="serverStrip__cell">
            <div className="serverStrip__cellLabel">스왑 사용</div>
            <div
              className={
                summary?.swap_used_mb
                  ? "serverStrip__cellValue serverStrip__cellValue--warn"
                  : "serverStrip__cellValue"
              }
            >
              {formatMb(summary?.swap_used_mb) ?? DASH}
            </div>
          </div>
          <div className="serverStrip__cell">
            <div className="serverStrip__cellLabel">가용 포트</div>
            <div className="serverStrip__cellValue">{portRange ?? DASH}</div>
          </div>
          <div className="serverStrip__cell">
            <div className="serverStrip__cellLabel">Docker</div>
            <div
              className={
                summary?.docker
                  ? "serverStrip__cellValue serverStrip__cellValue--ok"
                  : "serverStrip__cellValue"
              }
            >
              {summary?.docker ? "연결됨" : DASH}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Only appears when the disk is genuinely tight — the number that explains why
 * a build would fail, not a decorative warning strip.
 */
export function CapacityAlert({ summary }: { summary: SystemSummary | null }) {
  const warnings = summary?.performance_warnings || [];
  if (!warnings.includes("disk_low")) return null;
  const free = formatMb(summary?.disk_free_mb);
  const swap = warnings.includes("swap_active") ? formatMb(summary?.swap_used_mb) : null;

  return (
    <div className="capacityAlert" role="status">
      <span className="capacityAlert__icon" aria-hidden="true">
        <AlertCircle size={11} strokeWidth={2.6} />
      </span>
      <span>
        {free && <b>디스크 여유 {free}. </b>}
        새 서비스 빌드가 실패할 수 있습니다.
        {swap && ` 스왑 ${swap} 사용 중.`}
      </span>
    </div>
  );
}
