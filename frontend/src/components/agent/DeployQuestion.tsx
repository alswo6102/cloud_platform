import { AlertCircle, Check, ChevronDown } from "lucide-react";
import type { FieldContract, FrameworkPreset } from "../../types";
import "./DeployQuestion.css";

/** What the user already told the agent, folded back into one line. */
export function AnsweredLine({
  entries,
  onEdit
}: {
  entries: Array<{ label: string; value: string }>;
  onEdit?: (entry: { label: string; value: string }) => void;
}) {
  if (!entries.length) return null;
  const summary = entries.map((entry) => `${entry.label} ${entry.value}`).join(" · ");
  return (
    <div className="answeredLine">
      <span className="answeredLine__check" aria-hidden="true">
        <Check size={9} strokeWidth={3.4} />
      </span>
      <span className="truncate" title={summary}>
        {entries.map((entry, index) => (
          <span key={entry.label}>
            {index > 0 && " · "}
            {entry.label} <b>{entry.value}</b>
          </span>
        ))}
      </span>
      {onEdit && (
        <button className="answeredLine__edit" onClick={() => onEdit(entries[0])}>
          수정
        </button>
      )}
    </div>
  );
}

/**
 * A detected framework is shown as something to confirm, never as a value that
 * quietly became final.
 */
export function FrameworkSuggestion({
  suggestion,
  alternatives,
  showAll,
  onToggleAll,
  onConfirm,
  onPick,
  disabled
}: {
  suggestion: FrameworkPreset;
  alternatives: FrameworkPreset[];
  showAll: boolean;
  onToggleAll: () => void;
  onConfirm: () => void;
  onPick: (id: string) => void;
  disabled: boolean;
}) {
  const visible = showAll ? alternatives : alternatives.slice(0, 3);
  const hidden = alternatives.length - visible.length;

  return (
    <div className="suggestCard">
      <div className="suggestCard__head">
        <span className="suggestCard__kicker">제안 · 확인 필요</span>
      </div>
      <div className="suggestCard__body">
        <div className="suggestCard__row">
          <div className="suggestCard__pick">
            <div className="suggestCard__pickName">{suggestion.label}</div>
            {suggestion.description && (
              <div className="suggestCard__pickMeta truncate" title={suggestion.description}>
                {suggestion.description}
              </div>
            )}
          </div>
          <button className="btn btn--primary" onClick={onConfirm} disabled={disabled}>
            맞아요
          </button>
        </div>
        {alternatives.length > 0 && (
          <div className="suggestCard__alts">
            <span className="suggestCard__altsLabel">아니면</span>
            {visible.map((item) => (
              <button
                key={item.id}
                className="chip"
                onClick={() => onPick(item.id)}
                disabled={disabled}
              >
                {item.label}
              </button>
            ))}
            {(hidden > 0 || showAll) && (
              <button className="chip chip--plain" onClick={onToggleAll}>
                {showAll ? "접기" : `전체 ${alternatives.length + 1}종`}
                <ChevronDown size={12} aria-hidden="true" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The rules for the one field the server is asking about right now. */
export function QuestionHint({
  field,
  error
}: {
  field?: FieldContract;
  error?: string;
}) {
  if (error) {
    return (
      <div className="questionError">
        <span className="questionError__icon" aria-hidden="true">
          <AlertCircle size={10} strokeWidth={2.8} />
        </span>
        <span>{error}</span>
      </div>
    );
  }
  if (!field?.rules) return null;
  return <div className="questionRules">{field.rules}</div>;
}
