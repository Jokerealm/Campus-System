from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

SMOKE_KEY = "test-only-llm-key-for-smoke"


def main() -> None:
    previous_env = {
        "CAMPUS_LLM_BASE_URL": os.environ.get("CAMPUS_LLM_BASE_URL"),
        "CAMPUS_LLM_API_KEY": os.environ.get("CAMPUS_LLM_API_KEY"),
        "CAMPUS_LLM_MODEL": os.environ.get("CAMPUS_LLM_MODEL"),
    }
    os.environ["CAMPUS_LLM_BASE_URL"] = "https://example.invalid/v1"
    os.environ["CAMPUS_LLM_API_KEY"] = SMOKE_KEY
    os.environ["CAMPUS_LLM_MODEL"] = "campus-smoke-model"

    try:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        status_response = client.get("/api/model/status")
        assert status_response.status_code == 200, status_response.text
        status_payload = status_response.json()
        assert status_payload["enabled"] is True
        assert status_payload["model"] == "campus-smoke-model"

        readiness_response = client.get("/api/demo/readiness")
        assert readiness_response.status_code == 200, readiness_response.text
        readiness_payload = readiness_response.json()["data"]
        llm_component = next(
            item for item in readiness_payload["components"] if item["key"] == "llm"
        )
        assert llm_component["status"] == "ready"
        assert readiness_payload["llm"]["enabled"] is True
        assert readiness_payload["llm"]["model"] == "campus-smoke-model"

        combined = json.dumps(
            {"status": status_payload, "readiness": readiness_payload},
            ensure_ascii=False,
            sort_keys=True,
        )
        assert SMOKE_KEY not in combined
        assert "CAMPUS_LLM_API_KEY" not in combined

        print("llm config smoke passed")
        print("model_status_enabled=true")
        print(f"readiness_llm_status={llm_component['status']}")
        print("api_key_leaked=false")
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
