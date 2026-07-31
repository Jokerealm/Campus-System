from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from campus_p2_core.contracts.p2 import (
    P2ExamAnalysis,
    PracticePackResult,
    PracticeRecommendationGroup,
    QuestionRecommendation,
)


def attach_practice_recommendations(
    analysis: P2ExamAnalysis,
    *,
    p3_base_url: str = "",
    fixture_root: str | Path | None = None,
    service_id: str = "p2-service",
    auth_token: str = "",
    timeout_seconds: float = 5,
) -> P2ExamAnalysis:
    """Attach P3 practice recommendations while keeping P2 usable offline."""

    if not analysis.p3_search_requests:
        return analysis.model_copy(update={"practice_recommendations": []})

    knowledge_points, question_items = _load_fixture_catalog(fixture_root)
    groups: list[PracticeRecommendationGroup] = []

    for diagnostic in analysis.knowledge_diagnostics:
        if diagnostic.severity == "stable":
            continue

        knowledge_point = _match_knowledge_point(diagnostic.code, diagnostic.name, knowledge_points)
        knowledge_point_id = knowledge_point.get("knowledge_point_id", "")
        request = next(
            (
                item
                for item in analysis.p3_search_requests
                if diagnostic.code in item.knowledge_point_codes
            ),
            None,
        )
        if request is None:
            continue

        items: list[QuestionRecommendation] = []
        need_ai_generation = False
        source = "fixture"
        if p3_base_url:
            try:
                response = _search_p3_http(
                    p3_base_url=p3_base_url,
                    knowledge_point_id=knowledge_point_id,
                    request=request.model_dump(),
                    service_id=service_id,
                    auth_token=auth_token,
                    timeout_seconds=timeout_seconds,
                )
                items = [_recommendation_from_p3(item, diagnostic.name) for item in response["items"]]
                need_ai_generation = bool(response.get("need_ai_generation", False))
                source = "p3-http"
            except Exception:
                items = []
                need_ai_generation = True
                source = "fixture"

        if not items:
            fixture_matches = _search_fixture_questions(
                question_items,
                knowledge_point_id=knowledge_point_id,
                knowledge_point_code=diagnostic.code,
                limit=request.limit,
            )
            items = [_recommendation_from_fixture(item, diagnostic.name) for item in fixture_matches]
            need_ai_generation = len(items) < request.limit

        groups.append(
            PracticeRecommendationGroup(
                knowledge_point_code=diagnostic.code,
                knowledge_point_id=knowledge_point_id,
                knowledge_point_name=diagnostic.name,
                score_rate=diagnostic.score_rate,
                loss_rate=diagnostic.loss_rate,
                severity=diagnostic.severity,
                related_question_nos=diagnostic.related_question_nos,
                items=items,
                need_ai_generation=need_ai_generation,
                source=source,
            )
        )

    enriched_report = _append_recommendations_to_report(analysis, groups)
    return analysis.model_copy(
        update={
            "practice_recommendations": groups,
            "teaching_report": enriched_report,
        }
    )


def create_practice_pack(
    analysis: P2ExamAnalysis,
    *,
    title: str = "",
    target: str = "class",
    target_ref_id: str = "",
    created_by: str = "teacher_demo",
    p3_base_url: str = "",
    service_id: str = "p2-service",
    auth_token: str = "",
    timeout_seconds: float = 5,
) -> PracticePackResult:
    """Create a P3 practice pack from the current recommendation groups."""

    knowledge_point_ids, question_ids = _collect_pack_assets(analysis.practice_recommendations)
    pack_title = title or f"{analysis.class_name} 薄弱知识点强化训练"
    target_ref = target_ref_id or analysis.class_name or analysis.exam_id

    if not knowledge_point_ids or not question_ids:
        return PracticePackResult(
            practice_pack_id=f"pack_local_{uuid4().hex[:10]}",
            status="draft-local",
            title=pack_title,
            target=target,
            target_ref_id=target_ref,
            knowledge_point_ids=knowledge_point_ids,
            question_ids=question_ids,
            source="local",
            needs_p3_sync=True,
            message="推荐题或知识点不足，暂存为本地训练包草稿。",
        )

    if p3_base_url:
        try:
            payload = _create_practice_pack_http(
                p3_base_url=p3_base_url,
                title=pack_title,
                target=target,
                target_ref_id=target_ref,
                knowledge_point_ids=knowledge_point_ids,
                question_ids=question_ids,
                created_by=created_by,
                service_id=service_id,
                auth_token=auth_token,
                timeout_seconds=timeout_seconds,
            )
            return PracticePackResult(
                practice_pack_id=payload["practice_pack_id"],
                status=payload["status"],
                title=pack_title,
                target=target,
                target_ref_id=target_ref,
                knowledge_point_ids=knowledge_point_ids,
                question_ids=question_ids,
                source="p3-http",
                needs_p3_sync=False,
                message="训练包已写入 P3。",
            )
        except Exception as exc:
            return PracticePackResult(
                practice_pack_id=f"pack_local_{uuid4().hex[:10]}",
                status="draft-local",
                title=pack_title,
                target=target,
                target_ref_id=target_ref,
                knowledge_point_ids=knowledge_point_ids,
                question_ids=question_ids,
                source="local",
                needs_p3_sync=True,
                message=f"P3 暂不可用，已保留本地草稿：{exc}",
            )

    return PracticePackResult(
        practice_pack_id=f"pack_local_{uuid4().hex[:10]}",
        status="draft-local",
        title=pack_title,
        target=target,
        target_ref_id=target_ref,
        knowledge_point_ids=knowledge_point_ids,
        question_ids=question_ids,
        source="local",
        needs_p3_sync=True,
        message="未配置 P3 地址，已保留本地训练包草稿。",
    )


def save_generated_questions(
    *,
    source_question_id: str = "",
    items: list[dict[str, Any]],
    knowledge_point_version: str = "2026.1",
    model_name: str = "",
    prompt_version: str = "",
    raw_request: dict[str, Any] | None = None,
    p3_base_url: str,
    service_id: str = "p2-service",
    auth_token: str = "",
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Save AI-generated variants into P3's pending teacher-review queue."""

    if not p3_base_url:
        raise ValueError("p3_base_url is required")
    payload = {
        "source_question_id": source_question_id or None,
        "knowledge_point_version": knowledge_point_version,
        "model_name": model_name or "p2-generated-variant",
        "prompt_version": prompt_version or "p2.v0.1",
        "raw_request": raw_request or {},
        "items": items,
    }
    response = httpx.post(
        f"{p3_base_url.rstrip('/')}/api/resource/v1/generated-questions",
        headers=_p3_headers(service_id=service_id, auth_token=auth_token),
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK" or not isinstance(body.get("data"), dict):
        raise ValueError("P3 generated-question endpoint returned an invalid envelope")
    return body["data"]


def list_generated_questions(
    *,
    audit_status: str = "pending_review",
    knowledge_point_version: str = "2026.1",
    knowledge_point_id: str = "",
    limit: int = 50,
    p3_base_url: str,
    service_id: str = "p2-service",
    auth_token: str = "",
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Read AI-generated variants awaiting or after teacher review from P3."""

    if not p3_base_url:
        raise ValueError("p3_base_url is required")
    params: dict[str, Any] = {
        "knowledge_point_version": knowledge_point_version,
        "limit": limit,
    }
    if audit_status:
        params["audit_status"] = audit_status
    if knowledge_point_id:
        params["knowledge_point_id"] = knowledge_point_id
    response = httpx.get(
        f"{p3_base_url.rstrip('/')}/api/resource/v1/generated-questions",
        headers=_p3_headers(service_id=service_id, auth_token=auth_token),
        params=params,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK" or not isinstance(body.get("data"), dict):
        raise ValueError("P3 generated-question list returned an invalid envelope")
    return body["data"]


def review_generated_question(
    *,
    generated_question_id: str,
    decision: str,
    reviewer_id: str,
    review_comment: str = "",
    publish_to_bank: bool = True,
    p3_base_url: str,
    service_id: str = "p2-service",
    auth_token: str = "",
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Submit P2 teacher review decision for an AI-generated question."""

    if not p3_base_url:
        raise ValueError("p3_base_url is required")
    payload = {
        "decision": decision,
        "reviewer_id": reviewer_id,
        "review_comment": review_comment,
        "publish_to_bank": publish_to_bank,
    }
    response = httpx.put(
        f"{p3_base_url.rstrip('/')}/api/resource/v1/generated-questions/{generated_question_id}/review",
        headers=_p3_headers(service_id=service_id, auth_token=auth_token),
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK" or not isinstance(body.get("data"), dict):
        raise ValueError("P3 generated-question review returned an invalid envelope")
    return body["data"]


def _collect_pack_assets(groups: list[PracticeRecommendationGroup]) -> tuple[list[str], list[str]]:
    knowledge_point_ids: list[str] = []
    question_ids: list[str] = []
    for group in groups:
        if group.knowledge_point_id:
            knowledge_point_ids.append(group.knowledge_point_id)
        for item in group.items:
            if item.bank_question_id:
                question_ids.append(item.bank_question_id)
    return list(dict.fromkeys(knowledge_point_ids)), list(dict.fromkeys(question_ids))


def _create_practice_pack_http(
    *,
    p3_base_url: str,
    title: str,
    target: str,
    target_ref_id: str,
    knowledge_point_ids: list[str],
    question_ids: list[str],
    created_by: str,
    service_id: str,
    auth_token: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = {
        "title": title,
        "target": target,
        "target_ref_id": target_ref_id,
        "knowledge_point_ids": knowledge_point_ids,
        "knowledge_point_version": "2026.1",
        "question_ids": question_ids,
        "created_by": created_by,
    }
    url = f"{p3_base_url.rstrip('/')}/api/resource/v1/practice-packs"
    response = httpx.post(
        url,
        headers=_p3_headers(service_id=service_id, auth_token=auth_token),
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK" or not isinstance(body.get("data"), dict):
        raise ValueError("P3 practice-pack endpoint returned an invalid envelope")
    return body["data"]


def _search_p3_http(
    *,
    p3_base_url: str,
    knowledge_point_id: str,
    request: dict[str, Any],
    service_id: str,
    auth_token: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not knowledge_point_id:
        raise ValueError("knowledge_point_id is required for P3 HTTP search")
    payload = {
        "knowledge_point_ids": [knowledge_point_id],
        "knowledge_point_version": "2026.1",
        "question_type": request.get("question_type"),
        "difficulty_range": request.get("difficulty_range", [0.35, 0.75]),
        "source_priority": ["school_bank", "exam_history", "middle_exam_real"],
        "limit": request.get("limit", 5),
    }
    url = f"{p3_base_url.rstrip('/')}/api/resource/v1/questions/search"
    response = httpx.post(
        url,
        headers=_p3_headers(service_id=service_id, auth_token=auth_token),
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK" or not isinstance(body.get("data"), dict):
        raise ValueError("P3 search returned an invalid envelope")
    return body["data"]


def _p3_headers(*, service_id: str, auth_token: str) -> dict[str, str]:
    headers = {"X-Service-Id": service_id}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def _load_fixture_catalog(fixture_root: str | Path | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = Path(fixture_root) if fixture_root else _default_fixture_root()
    knowledge_path = root / "knowledge_points_2026_1.json"
    question_path = root / "question_bank_2026_1.json"
    knowledge_points = json.loads(knowledge_path.read_text(encoding="utf-8")) if knowledge_path.exists() else []
    question_groups = json.loads(question_path.read_text(encoding="utf-8")) if question_path.exists() else []
    question_items: list[dict[str, Any]] = []
    for group in question_groups:
        source = group.get("source", "school_bank")
        version = group.get("knowledge_point_version", "2026.1")
        for item in group.get("items", []):
            merged = dict(item)
            merged.setdefault("source", source)
            merged.setdefault("knowledge_point_version", version)
            question_items.append(merged)
    return knowledge_points, question_items


def _default_fixture_root() -> Path:
    return Path(__file__).resolve().parents[2] / "campus_p3" / "backend" / "resources" / "fixtures"


def _match_knowledge_point(code: str, name: str, knowledge_points: list[dict[str, Any]]) -> dict[str, Any]:
    for item in knowledge_points:
        if item.get("code") == code or item.get("knowledge_point_id") == code:
            return item
    for item in knowledge_points:
        if item.get("name") == name:
            return item
    for item in knowledge_points:
        if name and (name in item.get("name", "") or item.get("name", "") in name):
            return item
    return {}


def _search_fixture_questions(
    question_items: list[dict[str, Any]],
    *,
    knowledge_point_id: str,
    knowledge_point_code: str,
    limit: int,
) -> list[dict[str, Any]]:
    approved = [item for item in question_items if item.get("audit_status", "approved") == "approved"]
    matches = [
        item
        for item in approved
        if knowledge_point_id and knowledge_point_id in item.get("knowledge_point_ids", [])
    ]
    if not matches:
        matches = [
            item
            for item in approved
            if knowledge_point_code and knowledge_point_code in item.get("knowledge_point_ids", [])
        ]
    return sorted(matches, key=lambda item: (item.get("difficulty", 0.5), item.get("bank_question_id", "")))[:limit]


def _recommendation_from_p3(item: dict[str, Any], knowledge_name: str) -> QuestionRecommendation:
    return QuestionRecommendation(
        bank_question_id=item.get("bank_question_id", ""),
        source=item.get("source", "p3"),
        content_html=item.get("content_html", ""),
        answer_html=item.get("answer_html", ""),
        analysis_html=item.get("analysis_html", ""),
        knowledge_point_ids=list(item.get("knowledge_point_ids", [])),
        question_type=item.get("question_type", ""),
        difficulty=float(item.get("difficulty", 0.5)),
        match_score=float(item.get("match_score", 0.0)),
        recommend_reason=f"对应薄弱知识点：{knowledge_name}",
    )


def _recommendation_from_fixture(item: dict[str, Any], knowledge_name: str) -> QuestionRecommendation:
    return QuestionRecommendation(
        bank_question_id=item.get("bank_question_id", ""),
        source=item.get("source", "fixture"),
        content_html=item.get("content_html", ""),
        answer_html=item.get("answer_html", ""),
        analysis_html=item.get("analysis_html", ""),
        knowledge_point_ids=list(item.get("knowledge_point_ids", [])),
        question_type=item.get("question_type", ""),
        difficulty=float(item.get("difficulty", 0.5)),
        match_score=0.75,
        recommend_reason=f"本地题库样例，用于强化：{knowledge_name}",
    )


def _append_recommendations_to_report(
    analysis: P2ExamAnalysis,
    groups: list[PracticeRecommendationGroup],
):
    lines = [analysis.teaching_report.markdown.rstrip(), "", "## 推荐练习题"]
    if not groups:
        lines.append("- 暂无可推荐练习题。")
    for group in groups:
        if not group.items:
            lines.append(f"- {group.knowledge_point_name}：题库暂缺，建议进入 AI 变式题审核流程。")
            continue
        lines.append(f"- {group.knowledge_point_name}：推荐 {len(group.items)} 道。")
        for item in group.items[:3]:
            lines.append(f"  - {item.bank_question_id}：{_strip_html(item.content_html)}")
    return analysis.teaching_report.model_copy(update={"markdown": "\n".join(lines)})


def _strip_html(value: str) -> str:
    return (
        value.replace("<p>", "")
        .replace("</p>", "")
        .replace("<br>", " ")
        .replace("<br/>", " ")
        .replace("<br />", " ")
    )
