import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { ToolCall } from "../../types";

/**
 * One line saying which skill ran. Opened, it shows the few lines that support
 * the answer — never the raw preview payload the old panel printed.
 */
export function ToolBlock({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const expandable = call.evidence.length > 0;

  return (
    <div className={open ? "toolBlock toolBlock--open" : "toolBlock"}>
      <button
        className="toolBlock__head"
        onClick={() => expandable && setOpen(!open)}
        aria-expanded={expandable ? open : undefined}
        disabled={!expandable}
      >
        <span className="toolBlock__name">{call.skill}</span>
        <span>{call.summary}</span>
        {expandable && (
          <span className="toolBlock__chev" aria-hidden="true">
            {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </span>
        )}
      </button>
      {open && (
        <div className="toolBlock__body">
          <div className="toolBlock__label">근거 {call.evidence.length}줄</div>
          <div className="toolBlock__lines">
            {call.evidence.map((line, index) => (
              <div key={index}>{line}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
