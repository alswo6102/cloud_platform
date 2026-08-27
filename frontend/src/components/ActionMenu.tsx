import { useEffect, useRef } from "react";
import { MoreHorizontal } from "lucide-react";
import "./ActionMenu.css";

export type MenuItem = {
  id: string;
  label: string;
  /** `가역` or `승인 필요` — the cost of the action, said before it is taken. */
  hint?: string;
  danger?: boolean;
  section?: string;
};

export function ActionMenu({
  items,
  open,
  onOpenChange,
  onSelect,
  label,
  dropUp = false
}: {
  items: MenuItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (id: string) => void;
  label: string;
  dropUp?: boolean;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onOpenChange(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onOpenChange(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) {
      listRef.current?.querySelector<HTMLButtonElement>(".actionMenu__item")?.focus();
    }
  }, [open]);

  function moveFocus(direction: 1 | -1) {
    const nodes = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>(".actionMenu__item") || []
    );
    if (!nodes.length) return;
    const current = nodes.indexOf(document.activeElement as HTMLButtonElement);
    const next = (current + direction + nodes.length) % nodes.length;
    nodes[next]?.focus();
  }

  const groups: Array<{ section?: string; items: MenuItem[] }> = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.section === item.section) last.items.push(item);
    else groups.push({ section: item.section, items: [item] });
  }

  return (
    <div className="actionMenu" ref={rootRef}>
      <button
        className={open ? "btn btn--icon is-open" : "btn btn--icon"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => onOpenChange(!open)}
      >
        <MoreHorizontal size={15} aria-hidden="true" />
      </button>

      {open && (
        <div
          className={dropUp ? "actionMenu__pop actionMenu__pop--up" : "actionMenu__pop"}
          role="menu"
          ref={listRef}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              moveFocus(1);
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              moveFocus(-1);
            }
          }}
        >
          {groups.map((group, groupIndex) => (
            <div key={group.section ?? groupIndex}>
              {groupIndex > 0 && <div className="actionMenu__divider" />}
              {group.section && <div className="actionMenu__section">{group.section}</div>}
              {group.items.map((item) => (
                <button
                  key={item.id}
                  role="menuitem"
                  className={
                    item.danger ? "actionMenu__item actionMenu__item--danger" : "actionMenu__item"
                  }
                  onClick={() => {
                    onOpenChange(false);
                    onSelect(item.id);
                  }}
                >
                  {item.label}
                  {item.hint && <span className="actionMenu__hint">{item.hint}</span>}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
