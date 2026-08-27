"""Write .agent.env from the deploy script without discarding server-held values.

The deploy script renders the agent environment from whatever the operator has
in .env.local. An operator who deploys without an LLM key in their shell would
otherwise overwrite a working LLM_API_KEY with an empty one, and the platform
requires an LLM to answer anything at all. So an incoming blank value means
"keep whatever the server already had"; only a non-empty value replaces it.

Reads KEY=VALUE lines on stdin, merges them over the existing file, and writes
the result back to the path given as the single argument.
"""

from __future__ import annotations

import sys
from pathlib import Path


def parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value
    return values


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: merge_agent_env.py <path>", file=sys.stderr)
        return 2
    target = Path(sys.argv[1])
    existing = parse(target.read_text()) if target.is_file() else {}

    lines = []
    for line in sys.stdin.read().splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        lines.append(f"{key}={value or existing.get(key, '')}")

    target.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
