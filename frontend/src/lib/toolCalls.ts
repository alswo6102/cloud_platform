import type { AgentResponse, ToolCall } from "../types";
import { isRecord } from "./api";

const EVIDENCE_LINES = 3;

function tailLines(text: string, count = EVIDENCE_LINES) {
  return text
    .split("\n")
    .map((line) => line.trimEnd())
    .filter(Boolean)
    .slice(-count);
}

/**
 * Turns one skill run into the one-line block above the answer. The evidence is
 * a distilled few lines — the raw result object stays out of the conversation.
 */
function describe(skill: string, result: Record<string, unknown>): ToolCall {
  if (skill === "service.logs") {
    const logs = typeof result.logs === "string" ? result.logs : "";
    const evidence = tailLines(logs);
    const service = result.service ? String(result.service) : "";
    const requested = result.lines ? `${result.lines}줄` : "";
    const summary = ["실행함", service, requested].filter(Boolean).join(" · ");
    return { skill, summary, evidence };
  }

  if (skill === "service.status") {
    const services = Array.isArray(result.services) ? result.services : [];
    const evidence = services.slice(0, EVIDENCE_LINES).map((item) => {
      const record = isRecord(item) ? item : {};
      const container = isRecord(record.container) ? record.container : {};
      const name = String(record.service || "");
      const status = String(container.status || "확인 전");
      return `${name} ${status}`;
    });
    const summary = services.length ? `실행함 · 서비스 ${services.length}개` : "실행함";
    return { skill, summary, evidence };
  }

  if (skill === "project.list") {
    const projects = Array.isArray(result.projects) ? result.projects : [];
    const evidence = projects.slice(0, EVIDENCE_LINES).map((item) => {
      const record = isRecord(item) ? item : {};
      const services = Array.isArray(record.services) ? record.services.length : null;
      return [String(record.name || ""), services === null ? "" : `서비스 ${services}개`]
        .filter(Boolean)
        .join(" · ");
    });
    return {
      skill,
      summary: projects.length ? `실행함 · 프로젝트 ${projects.length}개` : "실행함",
      evidence
    };
  }

  if (skill === "repository.inspect") {
    const files = Array.isArray(result.files) ? result.files : [];
    return {
      skill,
      summary: files.length ? `실행함 · 파일 ${files.length}개` : "실행함",
      evidence: files.slice(0, EVIDENCE_LINES).map(String)
    };
  }

  if (skill === "server.health") {
    const evidence = [
      result.memory_percent !== undefined ? `메모리 ${result.memory_percent}%` : "",
      result.disk_percent !== undefined ? `디스크 ${result.disk_percent}%` : "",
      Array.isArray(result.restarting) && result.restarting.length
        ? `재시작 중 ${result.restarting.length}개`
        : ""
    ].filter(Boolean);
    return { skill, summary: "실행함 · 서버 상태", evidence };
  }

  return { skill, summary: "실행함", evidence: [] };
}

/**
 * Every skill this reply is built on, in the order it ran.
 *
 * The planner runs its read-only lookups inside its own loop and then writes
 * prose, so an answer used to arrive with nothing to show for the three skills
 * behind it. `tools` carries those runs. `skill` alone is not one of them — a
 * pending approval names the mutation it wants to run, which has not run.
 */
export function toolCallsFrom(data: AgentResponse): ToolCall[] {
  const calls: ToolCall[] = [];

  for (const step of data.tools ?? []) {
    if (!step?.skill) continue;
    calls.push(describe(step.skill, isRecord(step.result) ? step.result : {}));
  }

  if (data.skill && isRecord(data.result)) {
    calls.push(describe(data.skill, data.result));
  }

  const seen = new Set<string>();
  return calls.filter((call) => {
    const key = `${call.skill}|${call.summary}|${call.evidence.join("|")}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
