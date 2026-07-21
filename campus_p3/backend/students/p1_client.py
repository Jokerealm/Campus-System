"""Replaceable P1 client used by the student learning workflow.

The mock and HTTP implementations deliberately expose the same small interface so
that business views do not need to know whether P1 is available yet.
"""

import json
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings

from core.exceptions import AIServiceUnavailableError


def _normalize_job_status(status: Any) -> Any:
    if not isinstance(status, str):
        return None
    if status in {"succeeded", "completed", "success"}:
        return "succeeded"
    return status


class P1ClientProtocol(Protocol):
    def recognize_wrong_question(
        self,
        *,
        student_id: str,
        file: Mapping[str, Any],
        options: Mapping[str, Any],
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]: ...

    def get_wrong_question_result(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]: ...

    def get_job(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]: ...

    def guided_next(
        self,
        *,
        student_id: str,
        wrong_question_id: str,
        question_html: str,
        knowledge_point_ids: list[str],
        current_step_index: int,
        student_input: str,
        mode: str,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class P1HTTPClient:
    base_url: str
    timeout_seconds: float = 10.0
    service_id: str = "p3-service"
    auth_token: str = ""

    def __post_init__(self):
        if not self.base_url.strip():
            raise ValueError("P1 base URL must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("P1 timeout must be greater than zero")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    def recognize_wrong_question(
        self,
        *,
        student_id: str,
        file: Mapping[str, Any],
        options: Mapping[str, Any],
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/wrong-question/recognize",
            payload={
                "student_id": student_id,
                "file": dict(file),
                "options": dict(options),
            },
            request_id=request_id,
            tenant_id=tenant_id,
        )
        job_id = data.get("job_id")
        if not isinstance(job_id, str) or not job_id or len(job_id) > 128:
            raise AIServiceUnavailableError("AI service returned an invalid job ID")
        return {"job_id": job_id}

    def get_wrong_question_result(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/wrong-question/recognize/{quote(job_id, safe='')}/result",
            request_id=request_id,
            tenant_id=tenant_id,
        )

        # The v0.1 design returns the completed result directly. Some async P1
        # implementations wrap it in status/result; normalize both forms here.
        if "status" not in data:
            return {"status": "succeeded", "result": data}
        status = _normalize_job_status(data["status"])
        if status not in {
            "queued",
            "running",
            "succeeded",
            "failed",
            "cancelled",
        }:
            raise AIServiceUnavailableError(
                "AI service returned an invalid result status"
            )
        if "result" in data:
            return {"status": status, "result": data["result"]}
        if status == "succeeded":
            result = {key: value for key, value in data.items() if key != "status"}
            return {"status": "succeeded", "result": result}
        return {"status": status, "result": None}

    def get_job(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/jobs/{quote(job_id, safe='')}",
            request_id=request_id,
            tenant_id=tenant_id,
        )
        job_status = _normalize_job_status(data.get("status"))
        if job_status not in {"queued", "running", "succeeded", "failed", "cancelled"}:
            raise AIServiceUnavailableError("AI service returned an invalid job status")
        return {**data, "status": job_status}

    def guided_next(
        self,
        *,
        student_id: str,
        wrong_question_id: str,
        question_html: str,
        knowledge_point_ids: list[str],
        current_step_index: int,
        student_input: str,
        mode: str,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/explanations/guided/next",
            payload={
                "student_id": student_id,
                "wrong_question_id": wrong_question_id,
                "question_html": question_html,
                "knowledge_point_ids": knowledge_point_ids,
                "current_step_index": current_step_index,
                "student_input": student_input,
                "mode": mode,
            },
            request_id=request_id,
            tenant_id=tenant_id,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if request_id:
            headers["X-Request-Id"] = request_id
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id
        if self.service_id:
            headers["X-Service-Id"] = self.service_id
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read()
        except HTTPError as exc:
            raise AIServiceUnavailableError(
                f"AI service request failed with HTTP {exc.code}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise AIServiceUnavailableError("AI service is unavailable") from exc

        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIServiceUnavailableError(
                "AI service returned an invalid response"
            ) from exc

        if not isinstance(decoded, dict):
            raise AIServiceUnavailableError("AI service returned an invalid response")

        if "code" in decoded and decoded["code"] != "OK":
            raise AIServiceUnavailableError("AI service could not complete the request")
        data = decoded.get("data", decoded)
        if not isinstance(data, dict):
            raise AIServiceUnavailableError("AI service returned an invalid response")
        return data

    # More explicit aliases kept for callers that prefer the contract wording.
    submit_wrong_question_recognition = recognize_wrong_question
    get_wrong_question_recognition_result = get_wrong_question_result
    get_guided_explanation_next = guided_next


class MockP1Client:
    """Deterministic in-process P1 replacement for the first development phase."""

    _jobs: dict[str, dict[str, Any]] = {}
    _jobs_lock = threading.Lock()

    def recognize_wrong_question(
        self,
        *,
        student_id: str,
        file: Mapping[str, Any],
        options: Mapping[str, Any],
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        del file, options, request_id, tenant_id
        job_id = f"job_wrong_{uuid.uuid4().hex[:16]}"
        result = self._recognition_result(student_id)
        with self._jobs_lock:
            self._jobs[job_id] = result
        return {"job_id": job_id}

    def get_wrong_question_result(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        del request_id, tenant_id
        with self._jobs_lock:
            result = self._jobs.get(job_id)
        if result is None:
            # Mock jobs are intentionally ephemeral. Returning a stable fixture
            # also lets local data survive a development-server restart.
            result = self._recognition_result("stu_mock")
        return {"status": "succeeded", "result": result}

    def get_job(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        del request_id, tenant_id
        return {
            "job_id": job_id,
            "job_type": "wrong_question_recognition",
            "status": "succeeded",
            "progress": 100,
            "error": None,
        }

    def guided_next(
        self,
        *,
        student_id: str,
        wrong_question_id: str,
        question_html: str,
        knowledge_point_ids: list[str],
        current_step_index: int,
        student_input: str,
        mode: str,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        del (
            student_id,
            wrong_question_id,
            question_html,
            knowledge_point_ids,
            student_input,
            request_id,
            tenant_id,
        )
        content_by_mode = {
            "hint": "逐组选取最长边，比较另外两边之和是否严格大于它。",
            "check": (
                "注意三角形两边之和必须大于第三边，"
                "等于时也不能围成三角形。"
            ),
            "explain": (
                "判断三条线段能否围成三角形，"
                "只需验证较短两边之和是否大于最长边。"
            ),
            "summary": (
                "先找最长边，再用三角形两边之和大于第三边逐项判断。"
            ),
        }
        if mode not in content_by_mode:
            raise ValueError(f"Unsupported guided explanation mode: {mode}")
        return {
            "step_index": current_step_index + 1,
            "content": content_by_mode[mode],
            "next_action": "finish" if mode == "summary" else "ask_student",
            "can_show_full_answer": False,
        }

    @staticmethod
    def _recognition_result(student_id: str) -> dict[str, Any]:
        return {
            "student_id": student_id,
            "question": {
                "stem_text": (
                    "下列长度的三条线段首尾相接不能围成三角形的是（ ）"
                ),
                "stem_html": (
                    "<p>下列长度的三条线段首尾相接不能围成三角形的是（ ）"
                    "</p>"
                    "<p>A. 2, 3, 4　B. 8, 7, 15　C. 6, 8, 10　D. 13, 12, 20</p>"
                ),
                "question_type": "选择题",
                "images": [],
                "parse_confidence": 0.98,
                "needs_review": True,
            },
            "knowledge_candidates": [
                {
                    "knowledge_point_id": "kp_math_8_triangle_side_relation",
                    "knowledge_point_name": "三角形三边关系",
                    "confidence": 0.95,
                    "reason": (
                        "题目要求使用三角形任意两边之和"
                        "大于第三边进行判断。"
                    ),
                }
            ],
        }

    submit_wrong_question_recognition = recognize_wrong_question
    get_wrong_question_recognition_result = get_wrong_question_result
    get_guided_explanation_next = guided_next


def get_p1_client() -> P1ClientProtocol:
    mode = str(_setting("P1_CLIENT_MODE", "mock")).strip().lower()
    if mode == "mock":
        return MockP1Client()
    if mode in {"http", "real"}:
        try:
            timeout_seconds = float(_setting("P1_TIMEOUT_SECONDS", "10"))
        except (TypeError, ValueError) as exc:
            raise ValueError("P1_TIMEOUT_SECONDS must be a number") from exc
        return P1HTTPClient(
            base_url=str(
                _setting("P1_BASE_URL", "http://p1-ai-core:8101/api/ai/v1")
            ),
            timeout_seconds=timeout_seconds,
            service_id=str(_setting("P1_SERVICE_ID", "p3-service")),
            auth_token=str(_setting("P1_AUTH_TOKEN", "")),
        )
    raise ValueError(f"Unsupported P1_CLIENT_MODE: {mode}")


def _setting(name: str, default: str) -> Any:
    return getattr(settings, name, os.getenv(name, default))
