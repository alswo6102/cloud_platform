import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Modal } from "./Modal";
import { api } from "../lib/api";
import type { AuthHeaders, ServiceEnvEntry } from "../types";
import "./EnvModal.css";

/** Mirrors the server's own guess so a new row is labelled before it is saved. */
const SECRET_HINTS = [
  "SECRET",
  "KEY",
  "TOKEN",
  "PASSWORD",
  "PASSWD",
  "CREDENTIAL",
  "PRIVATE",
  "DSN",
  "DATABASE_URL"
];

export function looksSecret(name: string) {
  const upper = name.toUpperCase();
  return SECRET_HINTS.some((hint) => upper.includes(hint));
}

type Row = {
  key: number;
  name: string;
  /** What the user typed. Empty on a stored secret means "leave it alone". */
  value: string;
  secret: boolean;
  /** Already on the server: its name is fixed and a secret keeps its value. */
  stored: boolean;
  storedSet: boolean;
  touched: boolean;
};

let rowKey = 0;

function toRow(entry: ServiceEnvEntry): Row {
  return {
    key: rowKey++,
    name: entry.name,
    value: entry.secret ? "" : entry.value ?? "",
    secret: entry.secret,
    stored: true,
    storedSet: entry.is_set,
    touched: false
  };
}

export function EnvModal({
  project,
  service,
  auth,
  onClose,
  onSaved
}: {
  project: string;
  service: string;
  auth: AuthHeaders;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [removed, setRemoved] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [restart, setRestart] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api<{ result?: { entries?: ServiceEnvEntry[] } }>(
          `/api/projects/${project}/execute`,
          auth,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              skill: "service.env.list",
              arguments: { service },
              approved: true
            })
          }
        );
        if (cancelled) return;
        const entries = data.result?.entries || [];
        // Unset first: these are the ones a deploy registered but never filled,
        // and the reason someone opens this screen.
        const sorted = [...entries].sort((a, b) => {
          if (a.is_set !== b.is_set) return a.is_set ? 1 : -1;
          return a.name.localeCompare(b.name);
        });
        setRows(sorted.map(toRow));
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [project, service, auth]);

  const update = useCallback((key: number, patch: Partial<Row>) => {
    setRows((items) =>
      items.map((row) => (row.key === key ? { ...row, ...patch, touched: true } : row))
    );
  }, []);

  function addRow() {
    setRows((items) => [
      ...items,
      { key: rowKey++, name: "", value: "", secret: false, stored: false, storedSet: false, touched: true }
    ]);
  }

  function removeRow(row: Row) {
    if (row.stored) setRemoved((names) => [...names, row.name]);
    setRows((items) => items.filter((item) => item.key !== row.key));
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      // A stored secret left untouched is not resent: the console never had its
      // value, and sending an empty string would erase it.
      const entries = rows
        .filter((row) => row.name.trim())
        .filter((row) => !row.stored || row.touched || !row.secret)
        .filter((row) => !(row.stored && row.secret && !row.value))
        .map((row) => ({ name: row.name.trim(), value: row.value, secret: row.secret }));

      await api(`/api/projects/${project}/execute`, auth, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skill: "service.env.set",
          arguments: { service, entries, removals: removed, restart },
          approved: true
        })
      });
      onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setSaving(false);
    }
  }

  const unsetCount = rows.filter((row) => row.stored && !row.storedSet).length;

  return (
    <Modal title={`환경변수 · ${service}`} onClose={onClose} wide>
      {loading ? (
        <p className="envModal__loading">불러오는 중입니다</p>
      ) : (
        <div className="envModal">
          {unsetCount > 0 && (
            <p className="envModal__notice">
              값이 비어 있는 변수가 {unsetCount}개 있습니다. 배포할 때 이름만 등록된 것으로,
              지금 컨테이너에는 빈 문자열이 들어가 있습니다.
            </p>
          )}

          {rows.length === 0 ? (
            <p className="envModal__empty">등록된 환경변수가 없습니다.</p>
          ) : (
            <div className="envRows">
              <div className="envRows__head">
                <span>이름</span>
                <span>값</span>
                <span>비밀</span>
                <span />
              </div>
              {rows.map((row) => (
                <div className="envRow" key={row.key}>
                  <input
                    className="envRow__name"
                    value={row.name}
                    readOnly={row.stored}
                    placeholder="API_KEY"
                    onChange={(event) =>
                      update(row.key, {
                        name: event.target.value,
                        secret: row.touched ? row.secret : looksSecret(event.target.value)
                      })
                    }
                  />
                  <div className="envRow__valueCell">
                    <input
                      className="envRow__value"
                      type={row.secret ? "password" : "text"}
                      value={row.value}
                      placeholder={
                        row.stored && row.secret && row.storedSet ? "설정됨 · 새 값 입력 시 덮어씀" : ""
                      }
                      onChange={(event) => update(row.key, { value: event.target.value })}
                    />
                    {row.stored && !row.storedSet && <span className="envBadge">미설정</span>}
                  </div>
                  <label className="envRow__secret">
                    <input
                      type="checkbox"
                      checked={row.secret}
                      onChange={(event) => update(row.key, { secret: event.target.checked })}
                    />
                  </label>
                  <button
                    className="envRow__remove"
                    aria-label={`${row.name || "빈 행"} 삭제`}
                    onClick={() => removeRow(row)}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button className="envModal__add" onClick={addRow}>
            <Plus size={14} aria-hidden="true" />
            변수 추가
          </button>

          {error && <p className="envModal__error">{error}</p>}

          <p className="envModal__note">
            비밀로 저장한 값은 다시 표시되지 않습니다. 값을 바꾸려면 새로 입력해 덮어씁니다.
          </p>

          <div className="envModal__foot">
            <label className="envModal__restart">
              <input
                type="checkbox"
                checked={restart}
                onChange={(event) => setRestart(event.target.checked)}
              />
              저장 후 바로 적용 <span>컨테이너를 다시 만듭니다</span>
            </label>
            <div className="envModal__actions">
              <button className="btn" onClick={onClose} disabled={saving}>
                취소
              </button>
              <button className="btn btn--primary" onClick={save} disabled={saving}>
                {saving ? "저장 중" : "저장"}
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
