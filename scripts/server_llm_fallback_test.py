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
