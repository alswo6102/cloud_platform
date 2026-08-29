import { useEffect, useRef } from "react";
import { AlertCircle, Check, X } from "lucide-react";
import "./Modal.css";

/**
 * Login and project creation stay on top of the page they were started from —
 * neither gets a route, so closing returns you exactly where you were.
 */
export function Modal({
  title,
  onClose,
  wide,
  children
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  // Callers pass an inline arrow, so depending on it re-ran the effect below on
  // every render of the page behind the modal -- which stole the caret back to
  // the first field mid-typing, once per refresh.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    restoreRef.current = document.activeElement as HTMLElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.querySelector<HTMLInputElement>("input")?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      restoreRef.current?.focus?.();
    };
  }, []);

  return (
    <div
      className="modalBackdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={wide ? "modal modal--wide" : "modal"}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
      >
        <div className="modal__head">
          <span className="modal__title">{title}</span>
          <button className="modal__close" onClick={onClose} aria-label="닫기">
            <X size={14} aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  mono,
  valid,
  invalid,
  help,
  helpTone,
  autoComplete,
  onBlur
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  mono?: boolean;
  valid?: boolean;
  invalid?: boolean;
  help?: string;
  helpTone?: "ok" | "muted";
  autoComplete?: string;
  onBlur?: () => void;
}) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <span className={invalid ? "field__control field__control--invalid" : "field__control"}>
        <input
          className={mono ? "field__input field__input--mono" : "field__input"}
          value={value}
          type={type}
          placeholder={placeholder}
          autoComplete={autoComplete}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
        />
        {valid && (
          <span className="field__check" aria-hidden="true">
            <Check size={9} strokeWidth={3.4} />
          </span>
        )}
      </span>
      {help && (
        <span className={helpTone === "ok" ? "field__help field__help--ok" : "field__help"}>
          {help}
        </span>
      )}
    </label>
  );
}

export function FieldError({ children }: { children: React.ReactNode }) {
  return (
    <div className="field__error" role="alert">
      <span className="field__errorIcon" aria-hidden="true">
        <AlertCircle size={10} strokeWidth={2.8} />
      </span>
      <span>{children}</span>
    </div>
  );
}
