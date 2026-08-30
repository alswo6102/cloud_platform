#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

# The planner moved out of runtime; everything this exercises went with it.
import planner


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
            error = planner.requests.HTTPError(f"HTTP {self.status_code}")
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

# A finished answer, not a tool call. What these three checks are about is
# which model gets asked, and a tool call would send the planner round its loop
# against a fixture that answers the same thing every time -- twelve steps and
# a model list that no longer matches what was asked.
success = FakeResponse(
    200,
    {"choices": [{"message": {"content": "메모리 32%, 디스크 47%입니다."}}]},
)
limited = FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})

os.environ["LLM_API_KEY"] = "test"
os.environ["LLM_API_URL"] = "https://example.invalid"
os.environ["LLM_MODELS"] = "model-a,model-b"
os.environ.pop("LLM_MODEL", None)

planner.MODEL_COOLDOWNS.clear()
calls = []


def first_run(url, **kwargs):
    model = kwargs["json"]["model"]
    calls.append(model)
    return limited if model == "model-a" else success


with patch.object(planner.requests, "post", side_effect=first_run):
    result = planner.call_llm("서버 상태", skills)

assert calls == ["model-a", "model-b"], calls
assert result["model"] == "model-b", result
assert planner.llm_status()["cooldowns"]["model-a"] > 0
print("OK fallback_on_429")

calls.clear()
with patch.object(planner.requests, "post", side_effect=first_run):
    result = planner.call_llm("서버 상태", skills)

assert calls == ["model-b"], calls
assert result["model"] == "model-b", result
print("OK skip_model_during_cooldown")

planner.MODEL_COOLDOWNS.clear()
unauthorized = FakeResponse(401, {"error": {"status": "UNAUTHENTICATED"}})
calls.clear()


def auth_failure(url, **kwargs):
    calls.append(kwargs["json"]["model"])
    return unauthorized


# A 4xx retires the model that returned it and the list moves on, so a bad key
# exhausts every model rather than stopping at the first. That costs two futile
# requests and buys a failure that names all of them -- and the cooldowns it
# leaves are advisory, so the next request still tries them.
try:
    with patch.object(planner.requests, "post", side_effect=auth_failure):
        planner.call_llm("서버 상태", skills)
except planner.SkillError as exc:
    assert "model-a: 401" in str(exc), exc
    assert "model-b: 401" in str(exc), exc
else:
    raise AssertionError("a key that authenticates nowhere must not look like an answer")

assert calls == ["model-a", "model-b"], calls
print("OK auth_error_names_every_model_it_tried")

planner.MODEL_COOLDOWNS.clear()
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
        planner.requests,
        "post",
        side_effect=[discovery_response, reply_response],
    ),
    patch.object(
        # planner imports the name, so patching it on runtime patches nothing
        # the planner will actually call.
        planner,
        "execute_cli_skill",
        return_value={"frameworks": [{"id": "vite"}, {"id": "nextjs"}]},
    ) as cli_call,
):
    result = planner.call_llm(
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
with patch.object(planner.requests, "post", return_value=history_response) as post:
    result = planner.call_llm(
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
# Counted from the front, past the system prompt. The tail belongs to the
# planner's own loop -- the call this inspects is its last one, so by then it
# has appended its tool call and the result -- and what is being checked is
# that the history arrives ahead of the new message, in the order it was had.
payload_messages = post.call_args.kwargs["json"]["messages"]
assert payload_messages[0]["role"] == "system", payload_messages[0]
assert payload_messages[1]["content"] == "horse_race에 서비스를 배포할래"
assert payload_messages[2]["role"] == "assistant"
assert payload_messages[3]["content"] == "그걸로 진행해줘"
assert result["kind"] == "answer", result
print("OK llm_session_history")
