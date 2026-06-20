#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

import runtime


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            error = runtime.requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


skills = [
    {
        "name": "server.health",
        "document_name": "server-health",
        "description": "Inspect server health.",
        "instructions": "Use for server health requests.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
]

success = FakeResponse(
    200,
    {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "server-health",
                                "arguments": "{}",
                            }
                        }
                    ]
                }
            }
        ]
    },
)
limited = FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})

os.environ["LLM_API_KEY"] = "test"
os.environ["LLM_API_URL"] = "https://example.invalid"
os.environ["LLM_MODELS"] = "model-a,model-b"
os.environ.pop("LLM_MODEL", None)

runtime.MODEL_COOLDOWNS.clear()
calls = []


def first_run(url, **kwargs):
    model = kwargs["json"]["model"]
    calls.append(model)
    return limited if model == "model-a" else success


with patch.object(runtime.requests, "post", side_effect=first_run):
    result = runtime.call_llm("서버 상태", skills)

assert calls == ["model-a", "model-b"], calls
assert result["model"] == "model-b", result
assert runtime.llm_status()["cooldowns"]["model-a"] > 0
print("OK fallback_on_429")

calls.clear()
with patch.object(runtime.requests, "post", side_effect=first_run):
    result = runtime.call_llm("서버 상태", skills)

assert calls == ["model-b"], calls
assert result["model"] == "model-b", result
print("OK skip_model_during_cooldown")

runtime.MODEL_COOLDOWNS.clear()
unauthorized = FakeResponse(401, {"error": {"status": "UNAUTHENTICATED"}})
calls.clear()


def auth_failure(url, **kwargs):
    calls.append(kwargs["json"]["model"])
    return unauthorized


try:
    with patch.object(runtime.requests, "post", side_effect=auth_failure):
        runtime.call_llm("서버 상태", skills)
except runtime.requests.HTTPError:
    pass
else:
    raise AssertionError("401 must not fall back to another model")

assert calls == ["model-a"], calls
print("OK no_fallback_on_auth_error")

runtime.MODEL_COOLDOWNS.clear()
os.environ["LLM_MODELS"] = "model-a"
framework_skill = {
    "name": "framework.list",
    "document_name": "framework-list",
    "description": "List framework presets.",
    "instructions": "Use before explaining framework choices.",
    "schema": {"type": "object", "properties": {}, "additionalProperties": False},
}
discovery_response = FakeResponse(
    200,
    {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "framework-call",
                            "function": {
                                "name": "framework-list",
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            }
        ]
    },
)
reply_response = FakeResponse(
    200,
    {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "reply-call",
                            "function": {
                                "name": "conversation-reply",
                                "arguments": json.dumps(
                                    {
                                        "message": (
                                            "JavaScript는 Vite, React, Next.js, "
                                            "Express 중에서 선택해야 합니다."
                                        )
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    },
)

with (
    patch.object(
        runtime.requests,
        "post",
        side_effect=[discovery_response, reply_response],
    ),
    patch.object(
        runtime,
        "execute_cli_skill",
        return_value={"frameworks": [{"id": "vite"}, {"id": "nextjs"}]},
    ) as cli_call,
):
    result = runtime.call_llm(
        "프레임워크 프리셋 뭐 있어?",
        [framework_skill],
    )

assert result["kind"] == "answer", result
assert "Vite" in result["message"], result
cli_call.assert_called_once_with("framework.list", {}, dry_run=False)
print("OK discovery_tool_loop")

history_response = FakeResponse(
    200,
    {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "history-reply",
                            "function": {
                                "name": "conversation-reply",
                                "arguments": json.dumps(
                                    {"message": "이전 정보를 이어서 확인했습니다."},
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    },
)
with patch.object(runtime.requests, "post", return_value=history_response) as post:
    result = runtime.call_llm(
        "그걸로 진행해줘",
        [framework_skill],
        history=[
            {"role": "user", "content": "horse_race에 서비스를 배포할래"},
            {
                "role": "assistant",
                "content": "Static HTML / JavaScript 프리셋을 확인해주세요.",
            },
        ],
    )
payload_messages = post.call_args.kwargs["json"]["messages"]
assert payload_messages[-3]["content"] == "horse_race에 서비스를 배포할래"
assert payload_messages[-2]["role"] == "assistant"
assert payload_messages[-1]["content"] == "그걸로 진행해줘"
assert result["kind"] == "answer", result
print("OK llm_session_history")
