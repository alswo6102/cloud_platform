import { useState } from "react";
import type { AuthSession, Role } from "../types";
import { formatApiError } from "../lib/api";
import { Field, FieldError, Modal } from "./Modal";

export function LoginModal({
  onClose,
  onSuccess
}: {
  onClose: () => void;
  onSuccess: (session: NonNullable<AuthSession>) => void;
}) {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!userId.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId.trim(), password })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(formatApiError(data.detail) || "로그인에 실패했습니다.");
      if (!data.token) throw new Error("서버가 세션 토큰을 발급하지 않았습니다.");
      onSuccess({
        id: String(data.id),
        role: String(data.role || "user") as Role,
        name: data.name ? String(data.name) : undefined,
        token: String(data.token)
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="로그인" onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="modal__spacer" />
        <Field
          label="아이디"
          value={userId}
          onChange={setUserId}
          autoComplete="username"
          placeholder="사용자 ID"
        />
        <div className="modal__spacer" />
        <Field
          label="비밀번호"
          value={password}
          onChange={setPassword}
          type="password"
          autoComplete="current-password"
          invalid={Boolean(error)}
        />
        {error && <FieldError>{error}</FieldError>}
        <div className="modal__actions">
          <button
            className="btn btn--primary btn--lg btn--block"
            type="submit"
            disabled={busy || !userId.trim()}
          >
            {busy ? "확인 중..." : "로그인"}
          </button>
        </div>
        <p className="modal__note">닫으면 지금 보던 공개 목록으로 돌아갑니다.</p>
      </form>
    </Modal>
  );
}
