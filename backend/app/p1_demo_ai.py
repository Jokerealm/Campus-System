from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.knowledge_tagger import _clamp_confidence, _extract_json_object, _resolve_llm_model


P1_DEMO_JOBS: dict[str, dict[str, Any]] = {}


def create_wrong_question_recognition(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = f"job_wrong_{uuid4().hex[:16]}"
    result = _wrong_question_result(payload)
    P1_DEMO_JOBS[job_id] = _job_payload(
        job_id=job_id,
        job_type="wrong_question_recognition",
        status="succeeded",
        result=result,
    )
    return {"job_id": job_id}


def get_job(job_id: str) -> dict[str, Any]:
    job = P1_DEMO_JOBS.get(job_id)
    if job is None:
        return _job_payload(
            job_id=job_id,
            job_type="unknown",
            status="failed",
            error="job not found",
        )
    return {key: value for key, value in job.items() if key != "result"}


def get_wrong_question_result(job_id: str) -> dict[str, Any]:
    job = P1_DEMO_JOBS.get(job_id)
    if job is None:
        return {"status": "failed", "error": "job not found", "result": None}
    return {"status": job["status"], "result": job.get("result"), "error": job.get("error")}


def guided_explanation_next(
    payload: dict[str, Any],
    *,
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "openai-compatible",
    timeout_seconds: float = 8,
) -> dict[str, Any]:
    if llm_base_url and llm_api_key:
        try:
            return _llm_guided_explanation(
                payload,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            pass

    mode = payload.get("mode") or "hint"
    current = int(payload.get("current_step_index") or 0)
    question_text = _html_to_text(str(payload.get("question_html") or ""))
    topic = _infer_topic(question_text, payload.get("knowledge_point_ids") or [])
    templates = {
        "hint": f"先找出题目中与“{topic}”直接相关的条件，只做下一步转化，不急着写完整答案。",
        "check": f"检查你的式子是否同时用到了“{topic}”的核心条件，并注意单位、符号和范围。",
        "explain": f"这一步的关键是把题目文字转成“{topic}”对应的数学关系，再代入已知量。",
        "summary": f"完整思路：识别“{topic}”，列出条件，建立关系式，计算并回到题目要求检验结果。",
    }
    return {
        "step_index": current + 1,
        "content": templates.get(mode, templates["hint"]),
        "next_action": "finish" if mode == "summary" else "ask_student",
        "can_show_full_answer": mode == "summary",
    }


def generate_question_variants(
    payload: dict[str, Any],
    *,
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "openai-compatible",
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    count = min(max(int(payload.get("count") or 1), 1), 10)
    if llm_base_url and llm_api_key:
        try:
            items = _llm_variants(
                payload,
                count=count,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                timeout_seconds=timeout_seconds,
            )
            if items:
                return {"items": items[:count], "source": "llm"}
        except Exception:
            pass
    return {"items": [_fallback_variant(payload, index) for index in range(count)], "source": "heuristic"}


def _wrong_question_result(payload: dict[str, Any]) -> dict[str, Any]:
    student_id = str(payload.get("student_id") or "")
    file_payload = payload.get("file") or {}
    file_name = str(file_payload.get("file_name") or "")
    options = payload.get("options") or {}
    grade = str(options.get("grade") or "8")
    if "function" in file_name.lower() or "函数" in file_name:
        question = {
            "stem_text": "如图，在平面直角坐标系中，一次函数图像经过两个点，求函数关系式。",
            "stem_html": "<p>如图，在平面直角坐标系中，一次函数图像经过两个点，求函数关系式。</p>",
            "question_type": "解答题",
            "images": [],
            "parse_confidence": 0.78,
            "needs_review": True,
        }
        candidates = [
            {
                "knowledge_point_id": "kp_math_8_function_linear",
                "knowledge_point_name": "一次函数图像与性质",
                "confidence": 0.86,
                "reason": "题目涉及一次函数图像、坐标点和关系式求解。",
            }
        ]
    else:
        question = {
            "stem_text": "下列长度的三条线段首尾相接不能围成三角形的是（ ）",
            "stem_html": (
                "<p>下列长度的三条线段首尾相接不能围成三角形的是（ ）</p>"
                "<p>A. 2, 3, 4　B. 8, 7, 15　C. 6, 8, 10　D. 13, 12, 20</p>"
            ),
            "question_type": "选择题",
            "images": [],
            "parse_confidence": 0.82 if grade == "8" else 0.76,
            "needs_review": True,
        }
        candidates = [
            {
                "knowledge_point_id": "kp_math_8_triangle_side_relation",
                "knowledge_point_name": "三角形三边关系",
                "confidence": 0.9,
                "reason": "题目要求使用三角形任意两边之和大于第三边进行判断。",
            }
        ]
    return {"student_id": student_id, "question": question, "knowledge_candidates": candidates}


def _job_payload(
    *,
    job_id: str,
    job_type: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "progress": 100 if status == "succeeded" else 0,
        "created_at": now,
        "updated_at": now,
        "result_url": f"/api/ai/v1/wrong-question/recognize/{job_id}/result"
        if job_type == "wrong_question_recognition"
        else None,
        "error": error,
        "result": result,
    }


def _llm_guided_explanation(
    payload: dict[str, Any],
    *,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    resolved_model = _resolve_llm_model(llm_base_url, llm_api_key, llm_model, timeout_seconds)
    response = httpx.post(
        f"{llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {llm_api_key}", "Content-Type": "application/json"},
        json={
            "model": resolved_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是数学错题引导讲解助手。只给下一步提示，不直接泄露完整答案，除非 mode=summary。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question_html": payload.get("question_html", ""),
                            "knowledge_point_ids": payload.get("knowledge_point_ids", []),
                            "current_step_index": payload.get("current_step_index", 0),
                            "student_input": payload.get("student_input", ""),
                            "mode": payload.get("mode", "hint"),
                            "output_schema": {
                                "content": "short Chinese text",
                                "next_action": "ask_student|finish",
                                "can_show_full_answer": "boolean",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    parsed = _extract_json_object(response.json()["choices"][0]["message"]["content"])
    mode = payload.get("mode") or "hint"
    content = str(parsed.get("content") or "").strip()[:400]
    if not content:
        raise ValueError("empty guided explanation")
    return {
        "step_index": int(payload.get("current_step_index") or 0) + 1,
        "content": content,
        "next_action": parsed.get("next_action") if parsed.get("next_action") in {"ask_student", "finish"} else "ask_student",
        "can_show_full_answer": bool(parsed.get("can_show_full_answer")) if mode == "summary" else False,
    }


def _llm_variants(
    payload: dict[str, Any],
    *,
    count: int,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    resolved_model = _resolve_llm_model(llm_base_url, llm_api_key, llm_model, timeout_seconds)
    prompt = {
        "source_question_html": payload.get("source_question_html", ""),
        "knowledge_point_ids": payload.get("knowledge_point_ids", []),
        "difficulty_target": payload.get("difficulty_target", 0.55),
        "count": count,
        "constraints": payload.get("constraints", {}),
        "output_schema": {
            "items": [
                {
                    "content_html": "string",
                    "answer_html": "string",
                    "analysis_html": "string",
                    "difficulty": "0-1 number",
                    "validation": {"logic_checked": True, "answer_unique": True, "notes": []},
                }
            ]
        },
    }
    response = httpx.post(
        f"{llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {llm_api_key}", "Content-Type": "application/json"},
        json={
            "model": resolved_model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是数学教研命题助手。生成的变式题必须逻辑自洽，答案唯一，只输出 JSON。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.35,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    parsed = _extract_json_object(response.json()["choices"][0]["message"]["content"])
    items = []
    for raw in parsed.get("items") or []:
        items.append(_normalize_variant(payload, raw))
    return items


def _fallback_variant(payload: dict[str, Any], index: int) -> dict[str, Any]:
    knowledge_point_ids = list(payload.get("knowledge_point_ids") or [])
    difficulty = _clamp_confidence(payload.get("difficulty_target"), default=0.55)
    offset = index + 2
    if any("function" in item or "FUNC" in item for item in knowledge_point_ids):
        content = f"<p>已知一次函数 y={offset}x+1，求当 x={offset + 1} 时 y 的值。</p>"
        answer = f"<p>{offset * (offset + 1) + 1}</p>"
        analysis = "<p>把给定的 x 代入一次函数解析式，按运算顺序计算。</p>"
    else:
        content = f"<p>下列三条线段能围成三角形的是：{offset}, {offset + 1}, {offset + 2}。</p>"
        answer = "<p>能。</p>"
        analysis = "<p>较短两边之和大于最长边，因此可以围成三角形。</p>"
    return {
        "generated_question_id": f"genq_{uuid4().hex[:16]}",
        "content_html": content,
        "answer_html": answer,
        "analysis_html": analysis,
        "knowledge_point_ids": knowledge_point_ids,
        "difficulty": difficulty,
        "validation": {"logic_checked": True, "answer_unique": True, "notes": ["heuristic_demo"]},
        "audit_status": "pending_review",
    }


def _normalize_variant(payload: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_question_id": f"genq_{uuid4().hex[:16]}",
        "content_html": str(raw.get("content_html") or "<p>待补充题干。</p>"),
        "answer_html": str(raw.get("answer_html") or "<p>待教师审核答案。</p>"),
        "analysis_html": str(raw.get("analysis_html") or "<p>待教师审核解析。</p>"),
        "knowledge_point_ids": list(payload.get("knowledge_point_ids") or []),
        "difficulty": _clamp_confidence(raw.get("difficulty"), default=float(payload.get("difficulty_target") or 0.55)),
        "validation": raw.get("validation")
        if isinstance(raw.get("validation"), dict)
        else {"logic_checked": False, "answer_unique": False, "notes": ["llm_validation_missing"]},
        "audit_status": "pending_review",
    }


def _infer_topic(question_text: str, knowledge_point_ids: list[str]) -> str:
    joined_ids = " ".join(str(item) for item in knowledge_point_ids)
    text = f"{question_text} {joined_ids}"
    if "一次函数" in text or "FUNC" in text:
        return "一次函数图像与性质"
    if "三角形" in text or "triangle" in text:
        return "三角形三边关系"
    if "导数" in text:
        return "导数"
    return "当前知识点"


def _html_to_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()
