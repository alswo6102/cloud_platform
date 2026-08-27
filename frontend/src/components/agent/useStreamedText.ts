import { useEffect, useRef, useState } from "react";

/** Characters per second. Fast enough to read past, slow enough to see. */
const REVEAL_RATE = 900;

/**
 * The chat endpoint returns a finished answer in one response, so the text is
 * revealed here instead of arriving in pieces. Isolated in a hook on purpose:
 * when the backend grows an SSE route, only this file changes.
 */
export function useStreamedText(text: string, enabled: boolean) {
  const [shown, setShown] = useState(enabled ? "" : text);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) {
      setShown(text);
      return;
    }
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      setShown(text);
      return;
    }

    // Driven by elapsed time, not frame count: a throttled or backgrounded tab
    // then catches up in one frame instead of crawling a few characters a second.
    const startedAt = performance.now();
    setShown("");

    const step = (now: number) => {
      const target = Math.min(text.length, Math.ceil(((now - startedAt) / 1000) * REVEAL_RATE));
      setShown(text.slice(0, target));
      if (target < text.length) {
        frameRef.current = window.requestAnimationFrame(step);
      } else {
        frameRef.current = null;
      }
    };
    frameRef.current = window.requestAnimationFrame(step);

    return () => {
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
    };
  }, [text, enabled]);

  return { shown, done: shown.length >= text.length };
}
