#!/usr/bin/env python3
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from deployment_presets import FRAMEWORK_PRESETS, render_dockerfile

os.environ.setdefault("PROJECTS_ROOT", "/tmp/cloud-platform-router-projects")
Path(os.environ["PROJECTS_ROOT"]).mkdir(parents=True, exist_ok=True)

import app
import runtime


assert app.preferred_skill_for("신규 프로젝트를 만들고 싶어", None) == "project.create"
assert app.preferred_skill_for("서비스를 새로 배포하고 싶어", None) == "service.deploy"
assert app.preferred_skill_for("서비스를 최신 코드로 재배포해줘", None) == "service.redeploy"
print("OK intent_funnel")

ambiguous = app.ambiguity_for("서비스 다시 해줘", None)
assert ambiguous and len(ambiguous["choices"]) == 2, ambiguous
print("OK ambiguous_request_clarification")

guide = app.chat(app.ChatRequest(message="배포 절차 알려줘"))
assert guide["kind"] == "guide" and "프레임워크 프리셋" in guide["message"], guide
print("OK local_deployment_guide")

missing = runtime.service_deploy(
    None, None, None, None, None, True, None, None, True
)
assert missing["needs_input"], missing
assert "먼저 `신규 프로젝트를 만들어줘`" in missing["project_guidance"], missing
print("OK deployment_prerequisite")

for framework in FRAMEWORK_PRESETS:
    if framework == "existing":
        continue
    dockerfile = render_dockerfile(framework)
    assert "EXPOSE 3000" in dockerfile, framework
    assert dockerfile.strip(), framework
print("OK framework_templates")
