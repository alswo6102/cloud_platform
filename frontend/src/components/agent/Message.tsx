import { useEffect } from "react";
import type { AgentMessage } from "../../types";
import { useStreamedText } from "./useStreamedText";
import { ToolBlock } from "./ToolBlock";

/**
 * The agent replies in light markdown. Rendered as structure rather than raw
 * asterisks, with backticked values kept monospaced so a variable name in an
 * error stays recognisable.
 */
function renderInline(text: string, key: number) {
  const nodes: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={`${key}-${index++}`}>{token.slice(2, -2)}</strong>);
    } else {
      const value = token.slice(1, -1);
      const looksLikeEnvName = /^[A-Z][A-Z0-9_]{2,}$/.test(value);
      nodes.push(
        <code key={`${key}-${index++}`} className={looksLikeEnvName ? "is-error" : undefined}>
          {value}
        </code>
      );
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function AgentText({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  let bullets: string[] = [];

  const flush = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`}>
        {bullets.map((item, index) => (
          <li key={index}>
            <span>{renderInline(item, index)}</span>
          </li>
        ))}
      </ul>
    );
    bullets = [];
  };

  let fence: string[] | null = null;

  const flushFence = () => {
    if (!fence) return;
    blocks.push(
      <pre key={`pre-${blocks.length}`} className="msgCode">
        {fence.join("\n")}
      </pre>
    );
    fence = null;
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    // The model quotes logs in fences. Rendered as prose they arrived as three
    // literal backticks on a line of their own, above unwrapped log text.
    if (trimmed.startsWith("```")) {
      if (fence) flushFence();
      else {
        flush();
        fence = [];
      }
      return;
    }
    if (fence) {
      fence.push(line);
      return;
    }
    if (!trimmed) {
      flush();
      return;
    }
    if (trimmed.startsWith("- ")) {
      bullets.push(trimmed.slice(2));
      return;
    }
    flush();
    if (trimmed.startsWith("#")) {
      blocks.push(
        <p key={index}>
          <strong>{trimmed.replace(/^#+\s*/, "")}</strong>
        </p>
      );
      return;
    }
    blocks.push(<p key={index}>{renderInline(trimmed, index)}</p>);
  });
  flush();
  // An unterminated fence still has to render the lines it collected.
  flushFence();

  return <>{blocks}</>;
}

export function Message({
  message,
  streaming,
  onStreamEnd,
  children
}: {
  message: AgentMessage;
  streaming: boolean;
  onStreamEnd?: () => void;
  children?: React.ReactNode;
}) {
  const { shown, done } = useStreamedText(message.text, streaming);

  // Without this the cursor blinks for the rest of the session and every
  // unrelated re-render replays the reveal from the first character.
  useEffect(() => {
    if (streaming && done) onStreamEnd?.();
  }, [streaming, done, onStreamEnd]);

  if (message.from === "user") {
    return <div className="msgUser">{message.text}</div>;
  }

  return (
    <div className={message.tone === "error" ? "msgAgent msgAgent--error" : "msgAgent"}>
      {message.tools?.map((call, index) => (
        <ToolBlock key={`${index}-${call.skill}`} call={call} />
      ))}
      {shown && <AgentText text={shown} />}
      {streaming && !done && <span className="streamCursor" aria-hidden="true" />}
      {children}
    </div>
  );
}
