import { useState } from "react";
import type { AuthHeaders } from "../types";
import { api, errorText } from "../lib/api";
import { Field, FieldError, Modal } from "./Modal";

const NAME_PATTERN = /^[a-z0-9_]+$/;

/**
 * A project is a container for services, so the thing you actually came to do
 * is always the first deploy. The primary button says so.
 */
export function NewProjectModal({
  auth,
  onClose,
  onCreated
}: {
  auth: AuthHeaders;
  onClose: () => void;
  onCreated: (project: string, thenDeploy: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const trimmed = name.trim();
  const valid = NAME_PATTERN.test(trimmed);

  async function create(thenDeploy: boolean) {
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    try {
      // Preview first, then approve: the same two steps the CLI contract wants,
      // collapsed into one press because the plan is a single directory.
      await api("/api/projects", auth, {
        method: "POST",
        body: JSON.stringify({ name: trimmed, approved: false })
      });
      await api("/api/projects", auth, {
        method: "POST",
        body: JSON.stringify({ name: trimmed, approved: true })
      });
      onCreated(trimmed, thenDeploy);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="새 프로젝트" onClose={onClose} wide>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void create(true);
        }}
      >
        <div className="modal__spacer" />
        <Field
          label="이름"
          value={name}
          onChange={(value) => {
            setName(value);
            setError("");
          }}
          mono
          placeholder="horse_race_v2"
          valid={valid}
          invalid={Boolean(error)}
          help="소문자·숫자·밑줄 · 나중에 바꿀 수 없습니다"
        />
        {error && <FieldError>{error}</FieldError>}
        <div className="modal__actions">
          <button
            className="btn btn--primary btn--lg btn--block"
            type="submit"
            disabled={!valid || busy}
          >
            {busy ? "만드는 중..." : "만들고 서비스 배포"}
          </button>
          <button
            className="btn btn--md btn--block"
            type="button"
            onClick={() => void create(false)}
            disabled={!valid || busy}
          >
            만들기만
          </button>
        </div>
      </form>
    </Modal>
  );
}
