from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from campus_p2_core.p2_teacher.analyzer import FALLBACK_KNOWLEDGE_RULES


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_FIXTURE = (
    REPO_ROOT
    / "campus_p3"
    / "backend"
    / "resources"
    / "fixtures"
    / "knowledge_points_2026_1.json"
)

GENERIC_TERMS = {
    "数学",
    "初中数学",
    "高中数学",
    "数与代数",
    "图形与几何",
    "统计与概率",
    "综合与实践",
    "函数",
    "几何",
    "代数",
}


def tag_knowledge_questions(
    payload: dict[str, Any],
    *,
    p3_base_url: str = "",
    service_id: str = "p2-service",
    auth_token: str = "",
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "openai-compatible",
    timeout_seconds: float = 8,
) -> dict[str, Any]:
    """Return systemdesign-compatible knowledge candidates for P1 `/knowledge/tag`.

    The production contract is deliberately stable: P3 owns the dictionary, this
    helper only reads it and proposes candidates. If no LLM key is configured or
    the model fails, lexical matching keeps the first-stage demo deterministic.
    """

    subject = payload.get("subject") or "math"
    version = payload.get("knowledge_version") or "2026.1"
    candidate_limit = int(payload.get("candidate_limit") or 3)
    candidate_limit = min(max(candidate_limit, 1), 8)
    questions = list(payload.get("questions") or [])

    catalog, catalog_source = _load_knowledge_catalog(
        subject=subject,
        version=version,
        p3_base_url=p3_base_url,
        service_id=service_id,
        auth_token=auth_token,
        timeout_seconds=timeout_seconds,
    )
    catalog = [item for item in catalog if item.get("enabled", True)]

    rule_candidates_by_no: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        question_no = str(question.get("question_no", ""))
        rule_candidates_by_no[question_no] = _rule_candidates(question, catalog, candidate_limit)

    llm_enabled = bool(llm_api_key and llm_base_url)
    llm_candidates_by_no: dict[str, list[dict[str, Any]]] = {}
    llm_failures: list[str] = []
    if llm_enabled and questions:
        try:
            llm_candidates_by_no = _batch_llm_candidates(
                questions,
                rule_candidates_by_no,
                catalog,
                candidate_limit,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            llm_failures.append(f"batch:{exc}")

    items = []
    for question in questions:
        question_no = str(question.get("question_no", ""))
        candidates = rule_candidates_by_no.get(question_no, [])
        source = "heuristic"
        if llm_candidates_by_no.get(question_no):
            candidates = llm_candidates_by_no[question_no]
            source = "llm"

        top_confidence = max((item["confidence"] for item in candidates), default=0.0)
        items.append(
            {
                "question_no": question_no,
                "candidates": candidates,
                "needs_teacher_confirm": source != "llm" or top_confidence < 0.82,
                "model_version": llm_model if source == "llm" else "heuristic-p3-2026.1",
                "source": source,
            }
        )

    warnings = []
    if not catalog:
        warnings.append("knowledge_catalog_empty")
    if llm_failures:
        warnings.append(f"llm_fallback_count={len(llm_failures)}")

    return {
        "items": items,
        "knowledge_version": version,
        "catalog_source": catalog_source,
        "catalog_count": len(catalog),
        "llm_enabled": llm_enabled,
        "warnings": warnings,
    }


def _load_knowledge_catalog(
    *,
    subject: str,
    version: str,
    p3_base_url: str,
    service_id: str,
    auth_token: str,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], str]:
    if p3_base_url:
        headers = {"X-Service-Id": service_id}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        url = f"{p3_base_url.rstrip('/')}/api/resource/v1/knowledge-points"
        try:
            response = httpx.get(
                url,
                params={"subject": subject, "version": version, "enabled": "true"},
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("code") == "OK" and isinstance(body.get("data"), dict):
                items = body["data"].get("items") or []
                if isinstance(items, list) and items:
                    return items, "p3-http"
        except Exception:
            pass

    if DEFAULT_KNOWLEDGE_FIXTURE.exists():
        return json.loads(DEFAULT_KNOWLEDGE_FIXTURE.read_text(encoding="utf-8")), "fixture"
    return [], "empty"


def _rule_candidates(
    question: dict[str, Any],
    catalog: list[dict[str, Any]],
    candidate_limit: int,
) -> list[dict[str, Any]]:
    text = _question_text(question)
    scores: dict[str, dict[str, Any]] = {}
    by_code_or_name = _catalog_lookup(catalog)

    for keywords, (code, name) in FALLBACK_KNOWLEDGE_RULES:
        if any(keyword and keyword in text for keyword in keywords):
            item = by_code_or_name.get(code) or by_code_or_name.get(name)
            if item:
                _add_score(scores, item, 4.5, list(keywords), f"命中内置规则：{name}")

    for item in catalog:
        if _is_generic_knowledge_point(item):
            continue
        evidence: list[str] = []
        score = 0.0
        name = str(item.get("name") or "")
        if name and not _is_noise_term(name) and name in text:
            score += 4.0
            evidence.append(name)
        for part in item.get("path") or []:
            part_text = str(part)
            if part_text and part_text not in GENERIC_TERMS and not _is_noise_term(part_text) and part_text in text:
                score += 1.6
                evidence.append(part_text)
        for token in _knowledge_name_tokens(name):
            if token in text:
                score += 0.85
                evidence.append(token)
        if score:
            depth_bonus = min(len(item.get("path") or []), 4) * 0.18
            _add_score(scores, item, score + depth_bonus, evidence, "题干与知识点名称/路径存在词面匹配")

    if not scores:
        fallback = _first_non_generic(catalog)
        if fallback:
            _add_score(scores, fallback, 0.6, [], "未命中明确知识点，暂给出低置信度候选")

    ranked = sorted(
        scores.values(),
        key=lambda item: (
            item["raw_score"] + item["curated_bonus"],
            item["path_depth"],
            item["knowledge_point_id"],
        ),
        reverse=True,
    )[:candidate_limit]
    max_score = max((_effective_score(item) for item in ranked), default=1.0)
    candidates = []
    for item in ranked:
        confidence = 0.35 + 0.58 * (_effective_score(item) / max_score if max_score else 0)
        candidates.append(
            {
                "knowledge_point_id": item["knowledge_point_id"],
                "knowledge_point_name": item["knowledge_point_name"],
                "code": item["code"],
                "confidence": round(min(confidence, 0.93), 4),
                "reason": item["reason"],
                "evidence": sorted(set(item["evidence"]))[:6],
            }
        )
    return candidates


def _llm_candidates(
    question: dict[str, Any],
    rule_candidates: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    candidate_limit: int,
    *,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    shortlisted = _shortlist_for_llm(rule_candidates, catalog, candidate_limit)
    if not shortlisted:
        return []
    resolved_model = _resolve_llm_model(llm_base_url, llm_api_key, llm_model, timeout_seconds)
    prompt = {
        "task": "从候选知识点中选择最匹配的高中/初中数学知识点，最多返回指定数量。",
        "question": {
            "question_no": question.get("question_no", ""),
            "question_type": question.get("question_type", ""),
            "stem_text": question.get("stem_text", ""),
            "options": question.get("options", []),
        },
        "candidate_limit": candidate_limit,
        "knowledge_candidates": shortlisted,
        "output_schema": {
            "items": [
                {
                    "knowledge_point_id": "string",
                    "confidence": "0-1 number",
                    "reason": "short Chinese reason",
                    "evidence": ["short text evidence"],
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
                    "content": "你是数学教研知识点标注助手。只能从给定候选知识点中选择，不要编造 ID。只输出 JSON。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.1,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    message = body["choices"][0].get("message") or {}
    content = (message.get("content") or "").strip() or (message.get("reasoning_content") or "")
    try:
        parsed = _extract_json_object(content)
    except json.JSONDecodeError:
        return _freeform_candidates_from_content(content, shortlisted, candidate_limit)
    catalog_by_id = {item["knowledge_point_id"]: item for item in shortlisted}
    candidates = []
    for raw in parsed.get("items") or []:
        kp_id = str(raw.get("knowledge_point_id") or "")
        item = catalog_by_id.get(kp_id)
        if not item:
            continue
        candidates.append(
            {
                "knowledge_point_id": kp_id,
                "knowledge_point_name": item["knowledge_point_name"],
                "code": item["code"],
                "confidence": _clamp_confidence(raw.get("confidence"), default=0.78),
                "reason": str(raw.get("reason") or "模型根据题干语义匹配。")[:160],
                "evidence": [str(part)[:60] for part in (raw.get("evidence") or [])[:6]],
            }
        )
    if candidates:
        return candidates[:candidate_limit]
    return _freeform_candidates_from_content(content, shortlisted, candidate_limit)


def _batch_llm_candidates(
    questions: list[dict[str, Any]],
    rule_candidates_by_no: dict[str, list[dict[str, Any]]],
    catalog: list[dict[str, Any]],
    candidate_limit: int,
    *,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: float,
) -> dict[str, list[dict[str, Any]]]:
    batch_size = _safe_int(os.getenv("CAMPUS_LLM_TAG_BATCH_SIZE", "1"), default=1, minimum=1, maximum=16)
    if batch_size <= 1:
        return _parallel_single_question_llm_candidates(
            questions,
            rule_candidates_by_no,
            catalog,
            candidate_limit,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            timeout_seconds=timeout_seconds,
        )

    if len(questions) > batch_size:
        merged: dict[str, list[dict[str, Any]]] = {}
        failures: list[str] = []
        for start in range(0, len(questions), batch_size):
            chunk = questions[start : start + batch_size]
            try:
                merged.update(
                    _batch_llm_candidates(
                        chunk,
                        rule_candidates_by_no,
                        catalog,
                        candidate_limit,
                        llm_base_url=llm_base_url,
                        llm_api_key=llm_api_key,
                        llm_model=llm_model,
                        timeout_seconds=timeout_seconds,
                    )
                )
            except Exception as exc:
                fallback = _parallel_single_question_llm_candidates(
                    chunk,
                    rule_candidates_by_no,
                    catalog,
                    candidate_limit,
                    llm_base_url=llm_base_url,
                    llm_api_key=llm_api_key,
                    llm_model=llm_model,
                    timeout_seconds=timeout_seconds,
                )
                if fallback:
                    merged.update(fallback)
                else:
                    first_no = chunk[0].get("question_no", "") if chunk else ""
                    failures.append(f"{first_no}:{exc}")
        if merged:
            return merged
        if failures:
            raise RuntimeError("; ".join(failures[:3]))
        return {}

    question_payloads = []
    catalog_by_question: dict[str, dict[str, dict[str, Any]]] = {}
    for question in questions:
        question_no = str(question.get("question_no", ""))
        shortlisted = _shortlist_for_llm(rule_candidates_by_no.get(question_no, []), catalog, candidate_limit)
        if not shortlisted:
            continue
        catalog_by_question[question_no] = {item["knowledge_point_id"]: item for item in shortlisted}
        question_payloads.append(
            {
                "question_no": question_no,
                "question_type": question.get("question_type", ""),
                "stem_text": _truncate_text(str(question.get("stem_text") or ""), 1000),
                "options": [
                    {
                        "label": str(option.get("label") or ""),
                        "text": _truncate_text(str(option.get("text") or ""), 220),
                    }
                    for option in question.get("options") or []
                    if isinstance(option, dict)
                ],
                "knowledge_candidates": shortlisted,
            }
        )
    if not question_payloads:
        return {}

    resolved_model = _resolve_llm_model(llm_base_url, llm_api_key, llm_model, timeout_seconds)
    prompt = {
        "task": "为整套初中/高中数学试卷逐题标注知识点。只能从每题给定候选中选择，不要编造 ID。",
        "candidate_limit": candidate_limit,
        "questions": question_payloads,
        "output_schema": {
            "items": [
                {
                    "question_no": "string",
                    "candidates": [
                        {
                            "knowledge_point_id": "string",
                            "confidence": "0-1 number",
                            "reason": "short Chinese reason",
                            "evidence": ["short text evidence"],
                        }
                    ],
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
                    "content": "你是严谨的数学教研知识点标注助手。输出必须是 JSON，不输出解释文本。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.05,
            "max_tokens": min(max(1200, 220 * len(question_payloads)), 6000),
            "response_format": {"type": "json_object"},
        },
        timeout=max(timeout_seconds, 45),
    )
    response.raise_for_status()
    body = response.json()
    message = body["choices"][0].get("message") or {}
    content = (message.get("content") or "").strip() or (message.get("reasoning_content") or "")
    parsed = _extract_json_object(content)

    result: dict[str, list[dict[str, Any]]] = {}
    for tagged in parsed.get("items") or []:
        if not isinstance(tagged, dict):
            continue
        question_no = str(tagged.get("question_no") or "")
        allowed = catalog_by_question.get(question_no) or {}
        candidates = []
        for raw in tagged.get("candidates") or []:
            if not isinstance(raw, dict):
                continue
            kp_id = str(raw.get("knowledge_point_id") or "")
            item = allowed.get(kp_id)
            if not item:
                continue
            candidates.append(
                {
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": item["knowledge_point_name"],
                    "code": item["code"],
                    "confidence": _clamp_confidence(raw.get("confidence"), default=0.82),
                    "reason": str(raw.get("reason") or "模型根据题干语义匹配。")[:160],
                    "evidence": [str(part)[:60] for part in (raw.get("evidence") or [])[:6]],
                }
            )
        if candidates:
            result[question_no] = candidates[:candidate_limit]
    return result


def _parallel_single_question_llm_candidates(
    questions: list[dict[str, Any]],
    rule_candidates_by_no: dict[str, list[dict[str, Any]]],
    catalog: list[dict[str, Any]],
    candidate_limit: int,
    *,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: float,
) -> dict[str, list[dict[str, Any]]]:
    if not questions:
        return {}
    worker_count = _safe_int(os.getenv("CAMPUS_LLM_TAG_WORKERS", "4"), default=4, minimum=1, maximum=8)
    worker_count = min(worker_count, len(questions))
    resolved_model = _resolve_llm_model(llm_base_url, llm_api_key, llm_model, timeout_seconds)
    results: dict[str, list[dict[str, Any]]] = {}

    def tag_one(question: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        question_no = str(question.get("question_no", ""))
        candidates = _llm_candidates(
            question,
            rule_candidates_by_no.get(question_no, []),
            catalog,
            candidate_limit,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=resolved_model,
            timeout_seconds=max(timeout_seconds, 25),
        )
        return question_no, candidates

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(tag_one, question) for question in questions]
        for future in as_completed(futures):
            try:
                question_no, candidates = future.result()
            except Exception:
                continue
            if candidates:
                results[question_no] = candidates
    return results


def _resolve_llm_model(
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: float,
) -> str:
    model = (llm_model or "").strip()
    if model and model != "openai-compatible":
        return model
    response = httpx.get(
        f"{llm_base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {llm_api_key}"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    models = response.json().get("data") or []
    for item in models:
        model_id = item.get("id") if isinstance(item, dict) else None
        if model_id:
            return str(model_id)
    raise ValueError("LLM model is not configured and /models returned no model ids")


def _shortlist_for_llm(
    rule_candidates: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    candidate_limit: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items = []
    for candidate in rule_candidates:
        kp_id = candidate["knowledge_point_id"]
        seen.add(kp_id)
        items.append(
            {
                "knowledge_point_id": kp_id,
                "knowledge_point_name": candidate["knowledge_point_name"],
                "code": candidate.get("code", ""),
                "path": _catalog_path(catalog, kp_id),
            }
        )
    shortlist_limit = max(candidate_limit * 6, 18)
    for item in catalog:
        kp_id = str(item.get("knowledge_point_id") or "")
        if kp_id and kp_id not in seen and not _is_generic_knowledge_point(item):
            seen.add(kp_id)
            items.append(
                {
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": item.get("name", ""),
                    "code": item.get("code", ""),
                    "path": item.get("path", []),
                }
            )
        if len(items) >= shortlist_limit:
            break
    return items[:shortlist_limit]


def _truncate_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def _freeform_candidates_from_content(
    content: str,
    shortlisted: list[dict[str, Any]],
    candidate_limit: int,
) -> list[dict[str, Any]]:
    if not content:
        return []
    markers = ["最终", "答案", "返回", "选择", "推荐", "结果"]
    marker_positions = [content.rfind(marker) for marker in markers]
    start = max(marker_positions)
    tail = content[start:] if start >= 0 else content
    scored = []
    for item in shortlisted:
        probes = [
            str(item.get("knowledge_point_id") or ""),
            str(item.get("code") or ""),
            str(item.get("knowledge_point_name") or ""),
        ]
        positions = [tail.find(probe) for probe in probes if probe]
        positions = [position for position in positions if position >= 0]
        if positions:
            scored.append((min(positions), item))
    if not scored and tail is not content:
        for item in shortlisted:
            probes = [
                str(item.get("knowledge_point_id") or ""),
                str(item.get("code") or ""),
                str(item.get("knowledge_point_name") or ""),
            ]
            positions = [content.find(probe) for probe in probes if probe]
            positions = [position for position in positions if position >= 0]
            if positions:
                scored.append((min(positions), item))
    ranked = [item for _, item in sorted(scored, key=lambda pair: pair[0])][:candidate_limit]
    return [
        {
            "knowledge_point_id": item["knowledge_point_id"],
            "knowledge_point_name": item["knowledge_point_name"],
            "code": item["code"],
            "confidence": round(max(0.68, 0.86 - index * 0.06), 4),
            "reason": "模型自然语言结果中指向该知识点。",
            "evidence": [],
        }
        for index, item in enumerate(ranked)
    ]


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _question_text(question: dict[str, Any]) -> str:
    parts = [
        str(question.get("stem_text") or ""),
        str(question.get("stem_html") or ""),
        str(question.get("question_type") or ""),
    ]
    for option in question.get("options") or []:
        if isinstance(option, dict):
            parts.append(str(option.get("text") or ""))
        else:
            parts.append(str(option))
    return re.sub(r"\s+", "", " ".join(parts))


def _catalog_lookup(catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup = {}
    for item in catalog:
        for key in ("knowledge_point_id", "code", "name"):
            value = item.get(key)
            if value:
                lookup[str(value)] = item
    return lookup


def _add_score(
    scores: dict[str, dict[str, Any]],
    item: dict[str, Any],
    score: float,
    evidence: list[str],
    reason: str,
) -> None:
    kp_id = str(item.get("knowledge_point_id") or item.get("code") or item.get("name"))
    current = scores.setdefault(
        kp_id,
        {
            "knowledge_point_id": kp_id,
            "knowledge_point_name": str(item.get("name") or kp_id),
            "code": str(item.get("code") or kp_id),
            "raw_score": 0.0,
            "path_depth": len(item.get("path") or []),
            "curated_bonus": _curated_bonus(item),
            "evidence": [],
            "reason": reason,
        },
    )
    current["raw_score"] += score
    current["evidence"].extend([part for part in evidence if part])
    if score >= current.get("best_score", 0):
        current["best_score"] = score
        current["reason"] = reason


def _curated_bonus(item: dict[str, Any]) -> float:
    kp_id = str(item.get("knowledge_point_id") or "")
    code = str(item.get("code") or "")
    if ".AUTO." in code or "_auto_" in kp_id:
        return -0.6
    if code.startswith(("MATH.", "KP-")):
        return 1.2
    return 0.0


def _effective_score(item: dict[str, Any]) -> float:
    return float(item["raw_score"]) + float(item.get("curated_bonus", 0.0))


def _knowledge_name_tokens(name: str) -> list[str]:
    return [
        token
        for token in re.split(r"[、与及和的（）()·\s]+", name)
        if len(token) >= 2 and token not in GENERIC_TERMS and not _is_noise_term(token)
    ]


def _is_generic_knowledge_point(item: dict[str, Any]) -> bool:
    name = str(item.get("name") or "")
    path = item.get("path") or []
    return name in GENERIC_TERMS or _is_noise_term(name) or len(path) <= 1


def _is_noise_term(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    return text.count("?") >= max(2, len(text) // 2)


def _first_non_generic(catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in catalog:
        if not _is_generic_knowledge_point(item):
            return item
    return catalog[0] if catalog else None


def _catalog_path(catalog: list[dict[str, Any]], knowledge_point_id: str) -> list[str]:
    for item in catalog:
        if item.get("knowledge_point_id") == knowledge_point_id:
            return list(item.get("path") or [])
    return []


def _extract_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _clamp_confidence(value: Any, *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return round(min(max(numeric, 0.0), 1.0), 4)
