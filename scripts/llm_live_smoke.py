from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_ALIAS = "openai-compatible"


def main() -> None:
    args = parse_args()
    load_dotenv(ROOT / ".env")

    base_url = os.getenv("CAMPUS_LLM_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("CAMPUS_LLM_API_KEY", "").strip()
    configured_model = os.getenv("CAMPUS_LLM_MODEL", DEFAULT_MODEL_ALIAS).strip() or DEFAULT_MODEL_ALIAS
    timeout_seconds = float(os.getenv("CAMPUS_LLM_TIMEOUT_SECONDS", str(args.timeout_seconds)))

    if not base_url or not api_key:
        message = "llm live smoke skipped: CAMPUS_LLM_BASE_URL or CAMPUS_LLM_API_KEY is not configured"
        if args.require:
            raise SystemExit(message)
        print(message)
        print("api_key_leaked=false")
        return

    client = httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_seconds,
    )
    try:
        model = resolve_model(client, configured_model)
        content = call_chat_completion(client, model)
    finally:
        client.close()

    if not content.strip():
        raise SystemExit("llm live smoke failed: empty completion")

    combined = json.dumps(
        {"base_url": base_url, "configured_model": configured_model, "resolved_model": model, "content": content},
        ensure_ascii=False,
        sort_keys=True,
    )
    if api_key in combined or "CAMPUS_LLM_API_KEY" in combined:
        raise SystemExit("llm live smoke failed: API key leaked into output payload")

    print("llm live smoke passed")
    print(f"base_url_host={host_label(base_url)}")
    print(f"configured_model={configured_model}")
    print(f"resolved_model={model}")
    print(f"completion_chars={len(content)}")
    print("api_key_leaked=false")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Optionally perform a real OpenAI-compatible LLM call using CAMPUS_LLM_* "
            "from the environment or local .env. The API key is never printed."
        )
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Fail if LLM environment variables are missing. Without this flag the smoke test skips cleanly.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=15)
    return parser.parse_args()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_model(client: httpx.Client, configured_model: str) -> str:
    if configured_model and configured_model != DEFAULT_MODEL_ALIAS:
        return configured_model

    response = client.get("/models")
    response.raise_for_status()
    payload = response.json()
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise SystemExit("llm live smoke failed: /models did not return a data list")
    for item in models:
        if isinstance(item, dict) and item.get("id"):
            return str(item["id"])
    raise SystemExit("llm live smoke failed: no model id returned by /models")


def call_chat_completion(client: httpx.Client, model: str) -> str:
    response = client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是系统上线前的连通性自检助手。只输出 JSON。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "返回一个极短 JSON，证明模型可调用。",
                            "output_schema": {"ok": True, "message": "短中文字符串"},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
        },
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SystemExit("llm live smoke failed: completion response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not content and isinstance(message, dict):
        content = message.get("reasoning_content")
    if not isinstance(content, str):
        raise SystemExit("llm live smoke failed: completion message content is missing")
    return content


def host_label(base_url: str) -> str:
    without_scheme = base_url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0]


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        print("api_key_leaked=false")
        raise SystemExit(f"llm live smoke failed: {exc}") from exc
    except KeyboardInterrupt:
        sys.exit(130)
