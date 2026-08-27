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
 * Turns the skill the agent actually ran into the one-line block above its
 * answer. The evidence is a distilled few lines — the raw result object stays
 * out of the conversation.
 */
export function toolCallFrom(data: AgentResponse): ToolCall | null {
  const skill = data.skill;
  if (!skill) return null;
  const result = isRecord(data.result) ? data.result : {};

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
    return {
      skill,
      summary: projects.length ? `실행함 · 프로젝트 ${projects.length}개` : "실행함",
      evidence: []
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

  return { skill, summary: "실행함", evidence: [] };
}
