from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from html import unescape
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4
from urllib.parse import quote

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from campus_p2_core.contracts.p2 import KnowledgeDiagnostic, P2ExamAnalysis, P3SearchRequest, QuestionAnalysis
from campus_p2_core.p1_input.word_cutter import cut_docx_to_paper
from campus_p2_core.p2_teacher.analyzer import analyze_exam
from campus_p2_core.p2_teacher.p3_adapter import (
    attach_practice_recommendations,
    create_practice_pack,
    list_generated_questions,
    review_generated_question,
    save_generated_questions,
)
from campus_p2_core.p2_teacher.report_exporter import analysis_to_markdown, export_analysis_docx
from campus_p2_core.p2_teacher.score_loader import load_score_records
from app.knowledge_tagger import tag_knowledge_questions
from app.p1_demo_ai import (
    create_wrong_question_recognition,
    generate_question_variants,
    get_job as get_p1_demo_job,
    get_wrong_question_result,
    guided_explanation_next,
)
from app.persistence import P2SQLiteStore


app = FastAPI(title="campus-system-p2 API", version="1.0.0")

DATA_ROOT = REPO_ROOT / "data"
P1_PARSE_OUTPUT_ROOT = DATA_ROOT / "p1_parse_outputs"
P2_EXAM_OUTPUT_ROOT = DATA_ROOT / "p2_exams"
P2_DB_PATH = Path(os.getenv("CAMPUS_P2_SQLITE_PATH", str(DATA_ROOT / "p2_demo.sqlite3")))
if not P2_DB_PATH.is_absolute():
    P2_DB_PATH = REPO_ROOT / P2_DB_PATH

P1_PAPER_SUFFIXES = {".docx"}
SCORE_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".txt"}
P2_PAPER_SUFFIXES = {".json", ".docx"}
DEFAULT_MAX_PAPER_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_SCORE_UPLOAD_BYTES = 10 * 1024 * 1024

P1_PARSE_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
P2_EXAM_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

STORE = P2SQLiteStore(P2_DB_PATH)
EXAMS, FILES, DIAGNOSTICS = STORE.load_all()
LOCAL_GENERATED_QUESTIONS: dict[str, dict] = {}
P1_PARSE_JOBS: dict[str, dict[str, Any]] = {}
AI_KNOWLEDGE_TAG_JOBS: dict[str, dict[str, Any]] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    ],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount(
    "/api/assets/data/p1_parse_outputs",
    StaticFiles(directory=P1_PARSE_OUTPUT_ROOT),
    name="p1-parse-assets",
)


def _health_payload() -> dict:
    return {
        "ok": True,
        "app": "campus-system-p2",
        "contract": "paper.v0.1 + p2.v0.1",
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_p1_parse_job(job_id: str, job_type: str, result: dict[str, Any]) -> None:
    now = _utc_now_iso()
    result_url_map = {
        "paper_parse": f"/api/ai/v1/parse/paper/{job_id}/result",
        "score_excel_parse": f"/api/ai/v1/parse/score-excel/{job_id}/result",
    }
    P1_PARSE_JOBS[job_id] = {
        "job_id": job_id,
        "job_type": job_type,
        "status": result.get("status") or "succeeded",
        "progress": 100,
        "created_at": now,
        "updated_at": now,
        "result_url": result_url_map.get(job_type),
        "error": None,
        "result": result,
    }


def _p1_parse_job_result(job_id: str, *, expected_type: str) -> dict[str, Any]:
    job = P1_PARSE_JOBS.get(job_id)
    if job is None or job.get("job_type") != expected_type:
        return {"job_id": job_id, "status": "failed", "error": "job not found", "result": None}
    result = dict(job.get("result") or {})
    result.setdefault("job_id", job_id)
    result.setdefault("status", job.get("status") or "succeeded")
    return result


@app.get("/health")
def root_health() -> dict:
    return _health_payload()


@app.get("/api/health")
def health() -> dict:
    return _health_payload()


@app.post("/api/ai/v1/parse/paper")
async def p1_parse_paper(
    file: UploadFile = File(...),
    stage: str = Form("senior_high"),
    grade: str = Form(""),
) -> dict:
    content, upload_meta = await _read_validated_upload(
        file,
        allowed_suffixes=P1_PAPER_SUFFIXES,
        default_suffix=".docx",
        max_bytes=_configured_max_upload_bytes("CAMPUS_P1_MAX_PAPER_UPLOAD_BYTES", DEFAULT_MAX_PAPER_UPLOAD_BYTES),
        label="P1 Word 试卷",
    )

    job_id = f"p1_paper_{uuid4().hex[:10]}"
    job_root = P1_PARSE_OUTPUT_ROOT / job_id
    source_dir = job_root / "_source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"paper{upload_meta['suffix']}"
    source_path.write_bytes(content)

    try:
        paper, summary = cut_docx_to_paper(
            source_path,
            job_root,
            provider="campus_p1_word_cutter_api",
            stage=_normalize_stage(stage),
            grade=grade or _default_grade(stage),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    paper_id = paper["paper_id"]
    result = {
        "job_id": job_id,
        "status": "succeeded",
        "paper": paper,
        "questions": paper.get("questions", []),
        "global_warnings": paper.get("global_warnings", []),
        "summary": asdict(summary),
        "source_file": upload_meta,
        "paper_url": f"/api/assets/data/p1_parse_outputs/{job_id}/{paper_id}/paper.json",
        "asset_base_url": f"/api/assets/data/p1_parse_outputs/{job_id}/{paper_id}/assets",
    }
    _save_p1_parse_job(job_id, "paper_parse", result)
    return ok(result)


@app.get("/api/ai/v1/parse/paper/{job_id}/result")
def p1_parse_paper_result(job_id: str) -> dict:
    return ok(_p1_parse_job_result(job_id, expected_type="paper_parse"))


@app.post("/api/ai/v1/parse/score-excel")
async def p1_parse_score_excel(file: UploadFile = File(...)) -> dict:
    content, upload_meta = await _read_validated_upload(
        file,
        allowed_suffixes=SCORE_SUFFIXES,
        default_suffix=".xlsx",
        max_bytes=_configured_max_upload_bytes("CAMPUS_P1_MAX_SCORE_UPLOAD_BYTES", DEFAULT_MAX_SCORE_UPLOAD_BYTES),
        label="P1 成绩表",
    )

    job_id = f"p1_score_{uuid4().hex[:10]}"
    job_root = P1_PARSE_OUTPUT_ROOT / job_id
    job_root.mkdir(parents=True, exist_ok=True)
    source_path = job_root / f"scores{upload_meta['suffix']}"
    source_path.write_bytes(content)

    try:
        records = load_score_records(source_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    score_stats = [record.model_dump() for record in records]
    result = {
        "job_id": job_id,
        "status": "succeeded",
        "records": score_stats,
        "score_stats": score_stats,
        "global_warnings": [],
        "source_file": upload_meta,
        "summary": {"record_count": len(records)},
    }
    _save_p1_parse_job(job_id, "score_excel_parse", result)
    return ok(result)


@app.get("/api/ai/v1/parse/score-excel/{job_id}/result")
def p1_parse_score_excel_result(job_id: str) -> dict:
    return ok(_p1_parse_job_result(job_id, expected_type="score_excel_parse"))


class KnowledgeTagQuestionRequest(BaseModel):
    question_no: str
    stem_text: str = ""
    stem_html: str = ""
    question_type: str = ""
    options: list[dict] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)


class KnowledgeTaggingRequest(BaseModel):
    subject: str = "math"
    grade: str = ""
    knowledge_version: str = "2026.1"
    questions: list[KnowledgeTagQuestionRequest] = Field(default_factory=list)
    candidate_limit: int = 3


class P1FileObject(BaseModel):
    file_id: str
    storage_uri: str = ""
    file_name: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    sha256: str = ""


class WrongQuestionRecognizeRequest(BaseModel):
    student_id: str
    file: P1FileObject
    options: dict = Field(default_factory=dict)


class GuidedExplanationRequest(BaseModel):
    student_id: str
    wrong_question_id: str
    question_html: str
    knowledge_point_ids: list[str] = Field(default_factory=list)
    current_step_index: int = 0
    student_input: str = ""
    mode: str = "hint"


class QuestionVariantRequest(BaseModel):
    source_question_id: str = ""
    source_question_html: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty_target: float = 0.55
    count: int = 1
    constraints: dict = Field(default_factory=dict)


class StudentPracticeAnswerRequest(BaseModel):
    student_id: str = "student_demo"
    bank_question_id: str
    answer_text: str = ""
    is_correct: bool = False
    used_seconds: int = Field(default=0, ge=0, le=86_400)


class StudentWrongQuestionConfirmRequest(BaseModel):
    stem_html: str
    question_type: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)


class StudentExplanationNextRequest(BaseModel):
    current_step_index: int = Field(default=0, ge=0)
    student_input: str = ""
    mode: str = "hint"


@app.post("/api/ai/v1/knowledge/tag")
def p1_tag_knowledge(payload: KnowledgeTaggingRequest) -> dict:
    if not payload.questions:
        raise HTTPException(status_code=400, detail={"message": "questions cannot be empty"})
    result = tag_knowledge_questions(
        payload.model_dump(),
        p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
        service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
        auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
        llm_base_url=os.getenv("CAMPUS_LLM_BASE_URL", ""),
        llm_api_key=os.getenv("CAMPUS_LLM_API_KEY", ""),
        llm_model=os.getenv("CAMPUS_LLM_MODEL", "openai-compatible"),
        timeout_seconds=float(os.getenv("CAMPUS_LLM_TIMEOUT_SECONDS", "8")),
    )
    return ok(result)


@app.post("/api/ai/v1/wrong-question/recognize")
def p1_recognize_wrong_question(payload: WrongQuestionRecognizeRequest) -> dict:
    return ok(create_wrong_question_recognition(payload.model_dump()))


@app.get("/api/ai/v1/wrong-question/recognize/{job_id}/result")
def p1_wrong_question_result(job_id: str) -> dict:
    return ok(get_wrong_question_result(job_id))


@app.get("/api/ai/v1/jobs/{job_id}")
def p1_job_status(job_id: str) -> dict:
    parse_job = P1_PARSE_JOBS.get(job_id)
    if parse_job:
        return ok({key: value for key, value in parse_job.items() if key != "result"})
    return ok(get_p1_demo_job(job_id))


@app.post("/api/ai/v1/explanations/guided/next")
def p1_guided_explanation_next(payload: GuidedExplanationRequest) -> dict:
    result = guided_explanation_next(
        payload.model_dump(),
        llm_base_url=os.getenv("CAMPUS_LLM_BASE_URL", ""),
        llm_api_key=os.getenv("CAMPUS_LLM_API_KEY", ""),
        llm_model=os.getenv("CAMPUS_LLM_MODEL", "openai-compatible"),
        timeout_seconds=float(os.getenv("CAMPUS_LLM_TIMEOUT_SECONDS", "8")),
    )
    return ok(result)


@app.post("/api/ai/v1/questions/variants/generate")
def p1_generate_question_variants(payload: QuestionVariantRequest) -> dict:
    result = generate_question_variants(
        payload.model_dump(),
        llm_base_url=os.getenv("CAMPUS_LLM_BASE_URL", ""),
        llm_api_key=os.getenv("CAMPUS_LLM_API_KEY", ""),
        llm_model=os.getenv("CAMPUS_LLM_MODEL", "openai-compatible"),
        timeout_seconds=float(os.getenv("CAMPUS_LLM_TIMEOUT_SECONDS", "10")),
    )
    return ok(result)


class CreateExamRequest(BaseModel):
    name: str
    subject: str = "math"
    grade: str = ""
    class_ids: list[str] = Field(default_factory=list)
    exam_date: str = ""
    teacher_id: str = ""
    is_system_test: bool = False


class ParseExamRequest(BaseModel):
    score_file_id: str
    paper_file_id: str
    auto_tag_knowledge: bool = True


class RunDiagnosticsRequest(BaseModel):
    analysis_scope: str = "class"
    class_id: str = ""
    include_teaching_suggestions: bool = True
    include_question_recommendations: bool = True


class UpdateQuestionRequest(BaseModel):
    question_no: str | None = None
    stem_text: str | None = None
    stem_html: str | None = None
    question_type: str | None = None
    full_score: float | None = None
    options: list[dict] | None = None
    images: list[dict] | None = None


class KnowledgeTagsRequest(BaseModel):
    knowledge_point_ids: list[str] = Field(default_factory=list)
    comment: str = ""


class AiKnowledgeTagRequest(BaseModel):
    scope: str = "all"


class LessonPlanRequest(BaseModel):
    diagnostic_id: str
    template_id: str = "tpl_school_math_review_v1"
    sections: list[str] = Field(default_factory=list)


class CreatePracticePackRequest(BaseModel):
    diagnostic_id: str = ""
    title: str = ""
    target: str = "class"
    target_ref_id: str = ""
    created_by: str = ""


class GeneratedQuestionCandidateRequest(BaseModel):
    generated_question_id: str = ""
    content_html: str
    answer_html: str
    analysis_html: str
    knowledge_point_ids: list[str] = Field(default_factory=list)
    question_type: str = "solution"
    difficulty: float = 0.55
    images: list[dict] = Field(default_factory=list)
    validation: dict = Field(default_factory=dict)
    raw_response: dict = Field(default_factory=dict)


class SaveGeneratedQuestionsRequest(BaseModel):
    source_question_id: str = ""
    knowledge_point_version: str = "2026.1"
    model_name: str = "p2-generated-variant"
    prompt_version: str = "p2.v0.1"
    raw_request: dict = Field(default_factory=dict)
    items: list[GeneratedQuestionCandidateRequest] = Field(default_factory=list)


class ReviewGeneratedQuestionRequest(BaseModel):
    decision: str
    reviewer_id: str = ""
    review_comment: str = ""
    publish_to_bank: bool = True


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    role: str
    tenant_id: str
    auth_required: bool
    display_name: str = ""
    identity_source: str = "headers"
    directory_required: bool = False


ROLE_LABELS = {
    "teacher": "教师",
    "student": "学生",
    "service": "系统服务",
}

ROLE_PERMISSIONS = {
    "teacher": [
        ("exam:create", "创建考试"),
        ("exam:write", "上传与解析考试"),
        ("question:review", "教师确认题目"),
        ("practice-pack:write", "生成训练包"),
        ("lesson-plan:write", "生成教案"),
        ("ai-review:write", "审核 AI 题目"),
        ("audit:read", "查看系统审计"),
        ("student-support:read", "查看学生练习画像"),
    ],
    "student": [
        ("practice:read", "获取推荐练习"),
        ("practice:answer", "提交练习作答"),
        ("practice-history:read", "查看练习历史"),
        ("wrong-question:write", "上传和确认错题"),
        ("learning-report:read", "查看个人学习报告"),
    ],
    "service": [
        ("integration:read", "读取集成状态"),
        ("integration:write", "执行系统集成任务"),
        ("question-bank:proxy", "代理题库服务"),
        ("audit:write", "写入审计事件"),
    ],
}


def _identity_directory_path() -> Path | None:
    raw = os.getenv("CAMPUS_IDENTITY_DIRECTORY_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _builtin_identity_directory() -> dict:
    tenant_id = os.getenv("CAMPUS_DEFAULT_TENANT_ID", "demo_school")
    return {
        "source": "builtin_demo",
        "tenants": [{"tenant_id": tenant_id, "name": "Demo School"}],
        "users": [
            {
                "actor_id": os.getenv("CAMPUS_DEFAULT_TEACHER_ID", "teacher_demo"),
                "role": "teacher",
                "tenant_id": tenant_id,
                "display_name": "Demo Teacher",
                "active": True,
            },
            {
                "actor_id": os.getenv("CAMPUS_DEFAULT_STUDENT_ID", "student_demo"),
                "role": "student",
                "tenant_id": tenant_id,
                "display_name": "Demo Student",
                "active": True,
            },
            {
                "actor_id": os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
                "role": "service",
                "tenant_id": tenant_id,
                "display_name": "P2 Service",
                "active": True,
            },
        ],
    }


def _load_identity_directory() -> tuple[dict, str, bool]:
    path = _identity_directory_path()
    if path is None:
        return _builtin_identity_directory(), "builtin_demo", False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": f"账号目录不存在：{path}"},
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": f"账号目录 JSON 无法解析：{path}"},
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail={"message": "账号目录必须是 JSON object"})
    return payload, "configured_directory", True


def _find_identity_record(actor_id: str, role: str, tenant_id: str) -> tuple[dict | None, str, bool]:
    directory, source, configured = _load_identity_directory()
    users = directory.get("users", [])
    if not isinstance(users, list):
        raise HTTPException(status_code=503, detail={"message": "账号目录 users 必须是数组"})
    for user in users:
        if not isinstance(user, dict):
            continue
        if user.get("active", True) is False:
            continue
        user_actor_id = str(user.get("actor_id", "")).strip()
        user_role = str(user.get("role", "")).strip().lower()
        user_tenant_id = str(user.get("tenant_id", "")).strip()
        tenant_matches = user_tenant_id in {"", "*", tenant_id}
        if user_actor_id == actor_id and user_role == role and tenant_matches:
            return user, source, configured
    return None, source, configured


def _identity_directory_summary() -> dict:
    directory, source, configured = _load_identity_directory()
    users = directory.get("users", [])
    tenants = directory.get("tenants", [])
    active_users = [user for user in users if isinstance(user, dict) and user.get("active", True) is not False]
    return {
        "configured": configured,
        "source": source,
        "required": _env_flag("CAMPUS_IDENTITY_DIRECTORY_REQUIRED"),
        "tenant_count": len(tenants) if isinstance(tenants, list) else 0,
        "user_count": len(active_users),
        "roles": sorted({str(user.get("role", "")).strip() for user in active_users if user.get("role")}),
    }


def ok(data: dict, message: str = "success") -> dict:
    return {
        "request_id": f"req_{uuid4().hex[:12]}",
        "code": "OK",
        "message": message,
        "data": data,
    }


def actor_context(request: Request) -> ActorContext:
    auth_required = _env_flag("CAMPUS_AUTH_REQUIRED")
    configured_token = os.getenv("CAMPUS_P2_AUTH_TOKEN", "").strip()
    authorization = request.headers.get("authorization", "").strip()
    if auth_required and configured_token and authorization != f"Bearer {configured_token}":
        raise HTTPException(status_code=401, detail={"message": "缺少或无效的 P2 访问令牌"})

    teacher_id = request.headers.get("x-teacher-id", "").strip()
    service_id = request.headers.get("x-service-id", "").strip()
    student_id = request.headers.get("x-student-id", "").strip()
    actor_id = teacher_id or service_id or student_id
    if auth_required and not actor_id:
        raise HTTPException(status_code=401, detail={"message": "缺少操作者身份请求头"})

    requested_role = _normalize_actor_role(request.headers.get("x-client-role", ""), "teacher")
    role = "teacher" if teacher_id else "service" if service_id else "student" if student_id else requested_role
    if actor_id:
        resolved_actor_id = actor_id
    elif role == "student":
        resolved_actor_id = os.getenv("CAMPUS_DEFAULT_STUDENT_ID", "student_demo")
    elif role == "service":
        resolved_actor_id = os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service")
    else:
        resolved_actor_id = os.getenv("CAMPUS_DEFAULT_TEACHER_ID", "teacher_demo")
    tenant_id = request.headers.get("x-tenant-id", "").strip() or os.getenv("CAMPUS_DEFAULT_TENANT_ID", "demo_school")
    directory_required = auth_required and _env_flag("CAMPUS_IDENTITY_DIRECTORY_REQUIRED")
    identity_record, identity_source, directory_configured = _find_identity_record(resolved_actor_id, role, tenant_id)
    if directory_required and identity_record is None:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "账号不在允许的学校账号目录中",
                "actor_id": resolved_actor_id,
                "actor_role": role,
                "tenant_id": tenant_id,
                "identity_directory_configured": directory_configured,
            },
        )
    display_name = (
        str(identity_record.get("display_name", "")).strip()
        if isinstance(identity_record, dict)
        else ""
    )
    return ActorContext(
        actor_id=resolved_actor_id,
        role=role,
        tenant_id=tenant_id,
        auth_required=auth_required,
        display_name=display_name,
        identity_source=identity_source if identity_record else "headers",
        directory_required=directory_required,
    )


def _normalize_actor_role(requested_role: str, inferred_role: str) -> str:
    role = requested_role.strip().lower()
    return role if role in ROLE_PERMISSIONS else inferred_role


def _actor_payload(actor: ActorContext) -> dict:
    return {
        "actor_id": actor.actor_id,
        "actor_role": actor.role,
        "role_label": ROLE_LABELS.get(actor.role, actor.role),
        "tenant_id": actor.tenant_id,
        "display_name": actor.display_name,
        "identity_source": actor.identity_source,
    }


def _require_roles(actor: ActorContext, allowed_roles: set[str], action: str) -> None:
    if not actor.auth_required or actor.role in allowed_roles:
        return
    allowed_labels = "、".join(ROLE_LABELS.get(role, role) for role in sorted(allowed_roles))
    role_label = ROLE_LABELS.get(actor.role, actor.role)
    raise HTTPException(
        status_code=403,
        detail={
            "message": f"{role_label}无权执行：{action}",
            "actor_role": actor.role,
            "allowed_roles": sorted(allowed_roles),
            "allowed_labels": allowed_labels,
        },
    )


def _require_teacher_workspace(actor: ActorContext, action: str) -> None:
    _require_roles(actor, {"teacher", "service"}, action)


def _auth_mode(auth_required: bool, token_configured: bool) -> str:
    if not auth_required:
        return "demo_open"
    return "bearer_token" if token_configured else "identity_headers"


def _permissions_for_role(role: str) -> list[dict]:
    return [{"key": key, "label": label} for key, label in ROLE_PERMISSIONS.get(role, [])]


@app.get("/auth/session")
def auth_session(actor: ActorContext = Depends(actor_context)) -> dict:
    token_configured = bool(os.getenv("CAMPUS_P2_AUTH_TOKEN", "").strip())
    return ok(
        {
            "actor": _actor_payload(actor),
            "auth": {
                "auth_required": actor.auth_required,
                "token_configured": token_configured,
                "mode": _auth_mode(actor.auth_required, token_configured),
                "secret_visible": False,
                "identity_directory_required": actor.directory_required,
            },
            "identity_directory": _identity_directory_summary(),
            "permissions": _permissions_for_role(actor.role),
            "request_headers": {
                "tenant": "X-Tenant-Id",
                "teacher": "X-Teacher-Id",
                "student": "X-Student-Id",
                "role": "X-Client-Role",
                "authorization": "Authorization: Bearer <token>",
            },
        }
    )



def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@app.get("/student/practice/recommendations")
def student_practice_recommendations(
    student_id: str = "student_demo",
    limit: int = 5,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    if not resolved_student_id:
        raise HTTPException(status_code=400, detail={"message": "student_id cannot be empty"})
    limit = max(1, min(limit, 20))
    try:
        data = _p3_student_get(
            "/api/student/v1/practice/recommendations",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            params={"student_id": resolved_student_id, "limit": limit},
        )
        return ok(
            {
                "student_id": resolved_student_id,
                "source": "p3-http",
                "items": data.get("items", []),
            }
        )
    except Exception as exc:
        fallback = _student_practice_fallback(limit)
        fallback["detail"] = f"P3 学生练习暂不可用，已使用本地推荐兜底：{exc}"
        return ok({"student_id": resolved_student_id, **fallback})


@app.get("/student/practice/progress")
def student_practice_progress(
    student_id: str = "student_demo",
    recent_limit: int = 8,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    if not resolved_student_id:
        raise HTTPException(status_code=400, detail={"message": "student_id cannot be empty"})
    recent_limit = max(1, min(recent_limit, 20))
    try:
        data = _p3_student_get(
            "/api/student/v1/practice/progress",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            params={"student_id": resolved_student_id, "recent_limit": recent_limit},
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        return ok(
            {
                "student_id": resolved_student_id,
                "source": "local-fallback",
                "answer_count": 0,
                "correct_count": 0,
                "accuracy_rate": 0.0,
                "mastery_count": 0,
                "mastery": [],
                "recent_answers": [],
                "detail": f"P3 student progress is unavailable; using empty fallback: {exc}",
            }
        )


@app.get("/student/practice/history")
def student_practice_history(
    student_id: str = "student_demo",
    limit: int = 20,
    offset: int = 0,
    knowledge_point_id: str = "",
    is_correct: bool | None = None,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    if not resolved_student_id:
        raise HTTPException(status_code=400, detail={"message": "student_id cannot be empty"})
    params: dict[str, object] = {
        "student_id": resolved_student_id,
        "limit": max(1, min(limit, 100)),
        "offset": max(0, offset),
    }
    if knowledge_point_id.strip():
        params["knowledge_point_id"] = knowledge_point_id.strip()
    if is_correct is not None:
        params["is_correct"] = str(is_correct).lower()
    try:
        data = _p3_student_get(
            "/api/student/v1/practice/answers/history",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            params=params,
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        return ok(
            {
                "student_id": resolved_student_id,
                "source": "local-fallback",
                "total_count": 0,
                "limit": params["limit"],
                "offset": params["offset"],
                "items": [],
                "detail": f"P3 student answer history is unavailable; using empty fallback: {exc}",
            }
        )


@app.get("/student/reports/personal")
def student_personal_report(
    student_id: str = "student_demo",
    recent_limit: int = 8,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    if not resolved_student_id:
        raise HTTPException(status_code=400, detail={"message": "student_id cannot be empty"})
    recent_limit = max(1, min(recent_limit, 20))
    try:
        data = _p3_student_get(
            "/api/student/v1/reports/personal",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            params={"student_id": resolved_student_id, "recent_limit": recent_limit},
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        return ok(
            {
                "student_id": resolved_student_id,
                "source": "local-fallback",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "answer_count": 0,
                    "correct_count": 0,
                    "accuracy_rate": 0.0,
                    "wrong_question_count": 0,
                    "active_wrong_question_count": 0,
                    "mastered_wrong_question_count": 0,
                    "mastery_count": 0,
                    "average_mastery_rate": 0.0,
                    "report_level": "offline",
                },
                "mastery": {"weak": [], "strong": []},
                "wrong_question_status": {},
                "recent_wrong_questions": [],
                "recent_answers": [],
                "recommended_question_ids": [],
                "next_actions": [
                    {
                        "action_type": "connect_p3",
                        "title": "connect_p3",
                        "detail": f"P3 personal report is unavailable: {exc}",
                        "priority": "medium",
                        "knowledge_point_ids": [],
                    }
                ],
            }
        )


@app.post("/student/wrong-questions")
async def upload_student_wrong_question(
    request: Request,
    student_id: str = Form("student_demo"),
    subject: str = Form("math"),
    grade: str = Form("8"),
    image: UploadFile = File(...),
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    if not resolved_student_id:
        raise HTTPException(status_code=400, detail={"message": "student_id cannot be empty"})
    file_bytes = await image.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail={"message": "image cannot be empty"})
    try:
        data = _p3_student_upload(
            "/api/student/v1/wrong-questions",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            data={
                "student_id": resolved_student_id,
                "subject": subject or "math",
                "grade": grade or "8",
            },
            file_field="image",
            file_name=image.filename or "wrong-question.png",
            file_bytes=file_bytes,
            content_type=image.content_type or "application/octet-stream",
            idempotency_key=request.headers.get("idempotency-key", "").strip() or f"p2-wq-{uuid4().hex}",
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": f"P3 student wrong-question upload is unavailable: {exc}"},
        ) from exc


@app.get("/student/wrong-questions/{wrong_question_id}")
def get_student_wrong_question(
    wrong_question_id: str,
    student_id: str = "student_demo",
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    try:
        data = _p3_student_get(
            f"/api/student/v1/wrong-questions/{quote(wrong_question_id, safe='')}",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            params={},
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"message": f"P3 wrong-question detail is unavailable: {exc}"}) from exc


@app.put("/student/wrong-questions/{wrong_question_id}/confirm")
def confirm_student_wrong_question(
    wrong_question_id: str,
    payload: StudentWrongQuestionConfirmRequest,
    student_id: str = "student_demo",
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    request_payload = payload.model_dump()
    if not request_payload["knowledge_point_ids"]:
        raise HTTPException(status_code=400, detail={"message": "knowledge_point_ids cannot be empty"})
    try:
        data = _p3_student_put(
            f"/api/student/v1/wrong-questions/{quote(wrong_question_id, safe='')}/confirm",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            payload=request_payload,
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"message": f"P3 wrong-question confirmation is unavailable: {exc}"}) from exc


@app.post("/student/wrong-questions/{wrong_question_id}/explanation/next")
def student_wrong_question_explanation_next(
    wrong_question_id: str,
    payload: StudentExplanationNextRequest,
    student_id: str = "student_demo",
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (student_id or actor.actor_id or "student_demo").strip()
    try:
        data = _p3_student_post(
            f"/api/student/v1/wrong-questions/{quote(wrong_question_id, safe='')}/explanation/next",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            payload=payload.model_dump(),
            idempotency_key="",
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"message": f"P3 guided explanation is unavailable: {exc}"}) from exc


@app.post("/student/practice/answers")
def submit_student_practice_answer(
    payload: StudentPracticeAnswerRequest,
    request: Request,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    resolved_student_id = (payload.student_id or actor.actor_id or "student_demo").strip()
    if not resolved_student_id:
        raise HTTPException(status_code=400, detail={"message": "student_id cannot be empty"})
    request_payload = payload.model_dump()
    request_payload["student_id"] = resolved_student_id
    try:
        data = _p3_student_post(
            "/api/student/v1/practice/answers",
            student_id=resolved_student_id,
            tenant_id=actor.tenant_id,
            payload=request_payload,
            idempotency_key=request.headers.get("idempotency-key", "").strip() or f"p2-{uuid4().hex}",
        )
        return ok({"student_id": resolved_student_id, "source": "p3-http", **data})
    except Exception as exc:
        return ok(
            {
                "student_id": resolved_student_id,
                "source": "local-fallback",
                "answer_record_id": f"ans_local_{uuid4().hex[:12]}",
                "updated_mastery": [],
                "detail": f"P3 学生答题暂不可用，已保留本地提交回执：{exc}",
            }
        )


@app.post("/exams")
def create_exam(payload: CreateExamRequest, actor: ActorContext = Depends(actor_context)) -> dict:
    _require_teacher_workspace(actor, "创建考试")
    exam_id = f"exam_{uuid4().hex[:8]}"
    exam_payload = payload.model_dump()
    exam_payload["teacher_id"] = payload.teacher_id or actor.actor_id
    exam_payload["tenant_id"] = actor.tenant_id
    EXAMS[exam_id] = {
        "exam_id": exam_id,
        "status": "draft",
        "payload": exam_payload,
        "files": {},
        "analysis": None,
        "structure": None,
        "warnings": [],
        "lesson_plans": {},
        "practice_packs": [],
    }
    STORE.save_exam(EXAMS[exam_id])
    STORE.record_event(
        "exam_created",
        "exam",
        exam_id,
        {"teacher_id": exam_payload["teacher_id"], "grade": payload.grade, **_actor_payload(actor)},
    )
    return ok({"exam_id": exam_id, "status": "draft"})


@app.get("/exams")
def list_exams(
    limit: int = 24,
    include_system: bool = False,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    _require_teacher_workspace(actor, "查看考试列表")
    items = [
        _exam_summary(exam)
        for exam in EXAMS.values()
        if _actor_can_access_exam(exam, actor) and (include_system or not _is_system_test_exam(exam))
    ]
    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    items = items[: max(1, min(limit, 100))]
    return ok({"items": items})


@app.get("/exams/{exam_id}")
def get_exam(exam_id: str, actor: ActorContext = Depends(actor_context)) -> dict:
    return ok(_exam_summary(_exam_or_404(exam_id, actor)))


@app.post("/exams/{exam_id}/files")
async def upload_exam_file(
    exam_id: str,
    file_type: str = Form(...),
    file: UploadFile = File(...),
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if file_type not in {"score_excel", "paper"}:
        raise HTTPException(status_code=400, detail={"message": "file_type 必须为 score_excel 或 paper"})

    allowed_suffixes = SCORE_SUFFIXES if file_type == "score_excel" else P2_PAPER_SUFFIXES
    default_suffix = ".xlsx" if file_type == "score_excel" else ".json"
    max_bytes = _configured_max_upload_bytes(
        "CAMPUS_P2_MAX_SCORE_UPLOAD_BYTES" if file_type == "score_excel" else "CAMPUS_P2_MAX_PAPER_UPLOAD_BYTES",
        DEFAULT_MAX_SCORE_UPLOAD_BYTES if file_type == "score_excel" else DEFAULT_MAX_PAPER_UPLOAD_BYTES,
    )
    content, upload_meta = await _read_validated_upload(
        file,
        allowed_suffixes=allowed_suffixes,
        default_suffix=default_suffix,
        max_bytes=max_bytes,
        label="成绩表" if file_type == "score_excel" else "试卷文件",
    )
    file_id = f"file_{uuid4().hex[:10]}"
    metadata = {
        "file_id": file_id,
        "file_name": upload_meta["file_name"],
        "mime_type": file.content_type or "application/octet-stream",
        "size_bytes": upload_meta["size_bytes"],
        "storage_uri": f"local://exams/{exam_id}/{file_id}",
        "sha256": upload_meta["sha256"],
    }
    FILES[file_id] = {
        "exam_id": exam_id,
        "file_type": file_type,
        "metadata": metadata,
        "content": content,
    }
    exam["files"][file_type] = file_id
    STORE.save_file(FILES[file_id])
    STORE.save_exam(exam)
    STORE.record_event(
        "exam_file_uploaded",
        "file",
        file_id,
        {
            "exam_id": exam_id,
            "file_type": file_type,
            "file_name": metadata["file_name"],
            "size_bytes": metadata["size_bytes"],
            "sha256": metadata["sha256"],
            **_actor_payload(actor),
        },
    )
    return ok({"file": metadata})


@app.post("/exams/{exam_id}/parse")
def parse_exam(exam_id: str, payload: ParseExamRequest, actor: ActorContext = Depends(actor_context)) -> dict:
    exam = _exam_or_404(exam_id, actor)
    score = _file_or_404(payload.score_file_id, exam_id)
    paper = _file_or_404(payload.paper_file_id, exam_id)

    jobs = [
        {"job_id": f"job_score_{uuid4().hex[:8]}", "job_type": "score_excel_parse"},
        {"job_id": f"job_paper_{uuid4().hex[:8]}", "job_type": "paper_parse"},
    ]
    exam["jobs"] = jobs
    exam["status"] = "parsing"
    STORE.save_exam(exam)
    STORE.record_event(
        "exam_parse_started",
        "exam",
        exam_id,
        {"paper_file_id": payload.paper_file_id, "score_file_id": payload.score_file_id, **_actor_payload(actor)},
    )

    try:
        analysis = _enrich_analysis(_analyze_uploaded_pair(paper, score, exam_id, exam))
    except ValueError as exc:
        exam["status"] = "needs_p1"
        exam["warnings"] = [str(exc)]
        STORE.save_exam(exam)
        STORE.record_event("exam_parse_failed", "exam", exam_id, {"error": str(exc), **_actor_payload(actor)})
        return ok({"exam_id": exam_id, "status": "needs_p1", "jobs": jobs, "warnings": exam["warnings"]})

    exam["analysis"] = analysis
    exam["structure"] = _analysis_to_structure(exam_id, analysis)
    exam["status"] = "teacher_review"
    STORE.save_exam(exam)
    STORE.record_event(
        "exam_parse_succeeded",
        "exam",
        exam_id,
        {"question_count": len(exam["structure"].get("questions", [])), **_actor_payload(actor)},
    )
    return ok({"exam_id": exam_id, "status": "teacher_review", "jobs": jobs})


@app.get("/exams/{exam_id}/structure")
def get_exam_structure(exam_id: str, actor: ActorContext = Depends(actor_context)) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if exam.get("structure") is None:
        return ok(
            {
                "exam_id": exam_id,
                "status": exam["status"],
                "questions": [],
                "warnings": exam.get("warnings", []),
            }
        )
    exam["structure"]["status"] = exam["status"]
    return ok(exam["structure"])


@app.get("/exams/{exam_id}/analysis")
def get_exam_analysis(exam_id: str, actor: ActorContext = Depends(actor_context)) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=404, detail={"message": "考试分析尚未生成"})
    if exam.get("structure"):
        exam["analysis"] = _refresh_analysis_from_structure(exam)
        STORE.save_exam(exam)
    return ok(exam["analysis"].model_dump())


@app.put("/exams/{exam_id}/questions/{exam_question_id}")
def update_question(
    exam_id: str,
    exam_question_id: str,
    payload: UpdateQuestionRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    structure = exam.get("structure")
    if not structure:
        raise HTTPException(status_code=404, detail={"message": "考试结构尚未生成"})

    for question in structure["questions"]:
        if question["exam_question_id"] == exam_question_id:
            update = payload.model_dump(exclude_none=True)
            if "stem_html" in update and "stem_text" not in update:
                update["stem_text"] = _plain_text_from_html(update["stem_html"])
            if "images" in update:
                update["images"] = _normalize_question_images(update["images"])
            question.update(update)
            _sync_analysis_question(exam, exam_question_id, update)
            STORE.save_exam(exam)
            STORE.record_event(
                "question_structure_updated",
                "exam_question",
                exam_question_id,
                {"exam_id": exam_id, "fields": sorted(update.keys()), **_actor_payload(actor)},
            )
            return ok({"exam_question_id": exam_question_id, "updated": True})
    raise HTTPException(status_code=404, detail={"message": "题目不存在"})


@app.put("/exams/{exam_id}/questions/{exam_question_id}/knowledge-tags")
def confirm_knowledge_tags(
    exam_id: str,
    exam_question_id: str,
    payload: KnowledgeTagsRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    structure = exam.get("structure")
    if not structure:
        raise HTTPException(status_code=404, detail={"message": "考试结构尚未生成"})

    for question in structure["questions"]:
        if question["exam_question_id"] == exam_question_id:
            question["knowledge_point_ids"] = payload.knowledge_point_ids
            _sync_analysis_question(
                exam,
                exam_question_id,
                {"knowledge_point_ids": payload.knowledge_point_ids},
            )
            STORE.save_exam(exam)
            STORE.record_event(
                "knowledge_tags_confirmed",
                "exam_question",
                exam_question_id,
                {"exam_id": exam_id, "knowledge_point_ids": payload.knowledge_point_ids, **_actor_payload(actor)},
            )
            return ok(
                {
                    "exam_question_id": exam_question_id,
                    "knowledge_point_ids": payload.knowledge_point_ids,
                    "confirmed_by": actor.actor_id,
                    "confirmed_at": STORE.now(),
                }
            )
    raise HTTPException(status_code=404, detail={"message": "题目不存在"})


@app.post("/exams/{exam_id}/knowledge-tags/ai")
def start_ai_knowledge_tags(
    exam_id: str,
    payload: AiKnowledgeTagRequest,
    background_tasks: BackgroundTasks,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=409, detail={"message": "请先完成考试解析"})
    if not os.getenv("CAMPUS_LLM_API_KEY", "").strip() or not os.getenv("CAMPUS_LLM_BASE_URL", "").strip():
        raise HTTPException(status_code=409, detail={"message": "大模型接口尚未配置，无法智能校准知识点"})

    job_id = f"ai_kp_{uuid4().hex[:10]}"
    AI_KNOWLEDGE_TAG_JOBS[job_id] = {
        "job_id": job_id,
        "exam_id": exam_id,
        "status": "queued",
        "scope": payload.scope or "all",
        "message": "智能校准已开始",
        "updated_count": 0,
        "total_count": len(exam["analysis"].question_analysis),
        "created_at": STORE.now(),
        "updated_at": STORE.now(),
        "completed_at": None,
        "error": None,
    }
    STORE.record_event("ai_knowledge_tag_started", "exam", exam_id, {"job_id": job_id, **_actor_payload(actor)})
    background_tasks.add_task(_run_ai_knowledge_tag_job, job_id, exam_id, payload.scope or "all")
    return ok(AI_KNOWLEDGE_TAG_JOBS[job_id])


@app.get("/exams/{exam_id}/knowledge-tags/ai/{job_id}")
def get_ai_knowledge_tag_job(
    exam_id: str,
    job_id: str,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    _exam_or_404(exam_id, actor)
    job = AI_KNOWLEDGE_TAG_JOBS.get(job_id)
    if job is None or job.get("exam_id") != exam_id:
        raise HTTPException(status_code=404, detail={"message": "智能校准任务不存在"})
    return ok(job)


@app.post("/exams/{exam_id}/diagnostics/run")
def run_exam_diagnostics(
    exam_id: str,
    payload: RunDiagnosticsRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=409, detail={"message": "请先完成考试解析"})
    exam["analysis"] = _refresh_analysis_from_structure(exam)
    if payload.include_question_recommendations:
        exam["analysis"] = _enrich_analysis(exam["analysis"])
        exam["structure"] = _analysis_to_structure(exam_id, exam["analysis"])
    diagnostic_id = f"diag_{uuid4().hex[:8]}"
    DIAGNOSTICS[diagnostic_id] = {
        "exam_id": exam_id,
        "request": payload.model_dump(),
    }
    exam["status"] = "diagnosed"
    STORE.save_diagnostic(diagnostic_id, DIAGNOSTICS[diagnostic_id])
    STORE.save_exam(exam)
    STORE.record_event(
        "diagnostic_run",
        "diagnostic",
        diagnostic_id,
        {
            "exam_id": exam_id,
            "include_question_recommendations": payload.include_question_recommendations,
            **_actor_payload(actor),
        },
    )
    return ok({"diagnostic_id": diagnostic_id, "status": "succeeded"})


@app.get("/exams/{exam_id}/diagnostics/{diagnostic_id}")
def get_exam_diagnostic(
    exam_id: str,
    diagnostic_id: str,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    diagnostic = DIAGNOSTICS.get(diagnostic_id)
    if not diagnostic or diagnostic["exam_id"] != exam_id:
        raise HTTPException(status_code=404, detail={"message": "诊断报告不存在"})
    analysis: P2ExamAnalysis = exam["analysis"]
    return ok(_analysis_to_diagnostic(diagnostic_id, analysis))


@app.post("/exams/{exam_id}/practice-packs")
def create_exam_practice_pack(
    exam_id: str,
    payload: CreatePracticePackRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=409, detail={"message": "请先完成考试诊断"})
    if payload.diagnostic_id:
        diagnostic = DIAGNOSTICS.get(payload.diagnostic_id)
        if not diagnostic or diagnostic["exam_id"] != exam_id:
            raise HTTPException(status_code=404, detail={"message": "诊断报告不存在"})

    analysis: P2ExamAnalysis = exam["analysis"]
    if exam.get("structure"):
        analysis = _refresh_analysis_from_structure(exam)
    if not analysis.practice_recommendations:
        analysis = _enrich_analysis(analysis)

    result = create_practice_pack(
        analysis,
        title=payload.title,
        target=payload.target,
        target_ref_id=payload.target_ref_id or _class_name_from_exam(exam),
        created_by=payload.created_by or actor.actor_id,
        p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
        service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
        auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
        timeout_seconds=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )
    pack_payload = result.model_dump()
    pack_payload["created_at"] = STORE.now()
    exam.setdefault("practice_packs", []).append(pack_payload)
    exam["analysis"] = analysis.model_copy(
        update={"practice_packs": [*analysis.practice_packs, result]}
    )
    STORE.record_event(
        "practice_pack_created",
        "practice_pack",
        result.practice_pack_id,
        {"exam_id": exam_id, **_actor_payload(actor)},
    )
    STORE.save_exam(exam)
    return ok({"practice_pack": pack_payload})


@app.get("/exams/{exam_id}/practice-packs")
def list_exam_practice_packs(exam_id: str, actor: ActorContext = Depends(actor_context)) -> dict:
    exam = _exam_or_404(exam_id, actor)
    items = list(exam.get("practice_packs", []))
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return ok({"items": items})


@app.get("/ai-generated-questions")
def list_ai_generated_questions(
    status: str = "pending_review",
    knowledge_point_version: str = "2026.1",
    knowledge_point_id: str = "",
    limit: int = 50,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    _require_teacher_workspace(actor, "查看 AI 生成题审核队列")
    try:
        payload = list_generated_questions(
            audit_status=status,
            knowledge_point_version=knowledge_point_version,
            knowledge_point_id=knowledge_point_id,
            limit=limit,
            **_p3_runtime_config(),
        )
        return ok({**payload, "source": "p3-http"})
    except Exception:
        items = _local_generated_question_items(
            status=status,
            knowledge_point_version=knowledge_point_version,
            knowledge_point_id=knowledge_point_id,
            limit=limit,
        )
        return ok({"items": items, "source": "local"})


@app.get("/audit-logs")
def list_audit_logs(
    limit: int = 50,
    event: str = "",
    resource_type: str = "",
    resource_id: str = "",
    actor: ActorContext = Depends(actor_context),
) -> dict:
    _require_teacher_workspace(actor, "查看系统审计日志")
    return ok(
        {
            "items": STORE.list_events(
                limit=limit,
                event=event,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        }
    )


@app.post("/ai-generated-questions")
def save_ai_generated_questions(
    payload: SaveGeneratedQuestionsRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    _require_teacher_workspace(actor, "提交 AI 生成题审核")
    if not payload.items:
        raise HTTPException(status_code=400, detail={"message": "items cannot be empty"})
    normalized_items = [_generated_candidate_payload(item) for item in payload.items]
    try:
        result = save_generated_questions(
            source_question_id=payload.source_question_id,
            items=normalized_items,
            knowledge_point_version=payload.knowledge_point_version,
            model_name=payload.model_name,
            prompt_version=payload.prompt_version,
            raw_request=payload.raw_request,
            **_p3_runtime_config(),
        )
        STORE.record_event(
            "ai_generated_questions_submitted",
            "generated_question",
            payload.source_question_id or "batch",
            {"saved_count": result.get("saved_count", 0), "source": "p3-http", **_actor_payload(actor)},
        )
        return ok({**result, "source": "p3-http"})
    except Exception as exc:
        result = _save_local_generated_questions(payload, normalized_items, str(exc))
        STORE.record_event(
            "ai_generated_questions_submitted",
            "generated_question",
            payload.source_question_id or "batch",
            {"saved_count": result["saved_count"], "source": "local", **_actor_payload(actor)},
        )
        return ok(result)


@app.put("/ai-generated-questions/{generated_question_id}/review")
def review_ai_generated_question(
    generated_question_id: str,
    payload: ReviewGeneratedQuestionRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    _require_teacher_workspace(actor, "审核 AI 生成题")
    decision = payload.decision.strip()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail={"message": "decision must be approved or rejected"})
    reviewer_id = payload.reviewer_id or actor.actor_id
    try:
        result = review_generated_question(
            generated_question_id=generated_question_id,
            decision=decision,
            reviewer_id=reviewer_id,
            review_comment=payload.review_comment,
            publish_to_bank=payload.publish_to_bank,
            **_p3_runtime_config(),
        )
        STORE.record_event(
            "ai_generated_question_reviewed",
            "generated_question",
            generated_question_id,
            {"decision": decision, "source": "p3-http", "reviewer_id": reviewer_id, **_actor_payload(actor)},
        )
        return ok({**result, "source": "p3-http"})
    except Exception as exc:
        local_payload = payload.model_copy(update={"reviewer_id": reviewer_id})
        result = _review_local_generated_question(generated_question_id, local_payload, str(exc))
        STORE.record_event(
            "ai_generated_question_reviewed",
            "generated_question",
            generated_question_id,
            {"decision": decision, "source": "local", "reviewer_id": reviewer_id, **_actor_payload(actor)},
        )
        return ok(result)


@app.post("/exams/{exam_id}/lesson-plans")
def create_lesson_plan(
    exam_id: str,
    payload: LessonPlanRequest,
    actor: ActorContext = Depends(actor_context),
) -> dict:
    exam = _exam_or_404(exam_id, actor)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=409, detail={"message": "请先完成考试诊断"})
    diagnostic = DIAGNOSTICS.get(payload.diagnostic_id)
    if not diagnostic or diagnostic["exam_id"] != exam_id:
        raise HTTPException(status_code=404, detail={"message": "诊断报告不存在"})
    lesson_plan_id = f"lesson_{uuid4().hex[:8]}"
    filename = f"{exam_id}_lesson_plan.docx"
    output_dir = P2_EXAM_OUTPUT_ROOT / exam_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    export_analysis_docx(exam["analysis"], output_path)
    file_payload = {
        "file_id": f"file_lesson_{uuid4().hex[:8]}",
        "file_name": filename,
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "storage_uri": f"local://exams/{exam_id}/{filename}",
        "download_url": f"/exams/{exam_id}/lesson-plans/{lesson_plan_id}/download",
        "size_bytes": output_path.stat().st_size,
    }
    exam.setdefault("lesson_plans", {})[lesson_plan_id] = {
        "lesson_plan_id": lesson_plan_id,
        "diagnostic_id": payload.diagnostic_id,
        "request": payload.model_dump(),
        "file": file_payload,
        "path": str(output_path),
        "created_at": STORE.now(),
    }
    exam["status"] = "lesson_generated"
    STORE.record_event(
        "lesson_plan_generated",
        "lesson_plan",
        lesson_plan_id,
        {"exam_id": exam_id, **_actor_payload(actor)},
    )
    STORE.save_exam(exam)
    return ok(
        {
            "lesson_plan_id": lesson_plan_id,
            "status": "succeeded",
            "file": file_payload,
        }
    )


@app.get("/exams/{exam_id}/lesson-plans")
def list_lesson_plans(exam_id: str, actor: ActorContext = Depends(actor_context)) -> dict:
    exam = _exam_or_404(exam_id, actor)
    items = [_lesson_plan_summary(lesson_plan) for lesson_plan in exam.get("lesson_plans", {}).values()]
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return ok({"items": items})


@app.get("/exams/{exam_id}/lesson-plans/{lesson_plan_id}/download")
def download_lesson_plan(
    exam_id: str,
    lesson_plan_id: str,
    actor: ActorContext = Depends(actor_context),
) -> FileResponse:
    exam = _exam_or_404(exam_id, actor)
    lesson_plan = exam.get("lesson_plans", {}).get(lesson_plan_id)
    if not lesson_plan:
        raise HTTPException(status_code=404, detail={"message": "教案不存在"})
    output_path = Path(lesson_plan["path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail={"message": "教案文件不存在"})
    STORE.record_event(
        "lesson_plan_downloaded",
        "lesson_plan",
        lesson_plan_id,
        {"exam_id": exam_id, **_actor_payload(actor)},
    )
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=lesson_plan["file"]["file_name"],
    )


@app.get("/api/model/status")
def model_status() -> dict:
    llm_base_url = os.getenv("CAMPUS_LLM_BASE_URL", "")
    llm_model = os.getenv("CAMPUS_LLM_MODEL", "openai-compatible")
    p3_base_url = os.getenv("CAMPUS_P3_BASE_URL", "")
    return {
        "enabled": bool(os.getenv("CAMPUS_LLM_API_KEY")),
        "base_url": llm_base_url,
        "model": llm_model,
        "p3_base_url": p3_base_url,
        "note": "大模型使用 OpenAI-compatible 配置；未配置 key 时使用规则与 P1 知识点候选。",
    }


@app.get("/api/demo/readiness")
def demo_readiness() -> dict:
    return ok(_demo_readiness())


@app.get("/api/p2/demo")
def p2_demo() -> dict:
    analysis = analyze_exam(
        paper_json_path=REPO_ROOT / "examples" / "normalized_paper_demo.json",
        score_file_path=REPO_ROOT / "examples" / "sample_exam_scores.xlsx",
        exam_id="exam_demo_001",
        class_name="示例班级",
    )
    return _enrich_analysis(analysis).model_dump()


@app.get("/api/p2/examples/paper")
def download_example_paper() -> FileResponse:
    return FileResponse(
        REPO_ROOT / "examples" / "normalized_paper_demo.json",
        media_type="application/json",
        filename="normalized_paper_demo.json",
    )


@app.get("/api/p2/examples/scores")
def download_example_scores() -> FileResponse:
    return FileResponse(
        REPO_ROOT / "examples" / "sample_exam_scores.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="sample_exam_scores.xlsx",
    )


@app.post("/api/p2/analyze")
async def analyze_p2_upload(
    paper_file: UploadFile = File(...),
    score_file: UploadFile = File(...),
    exam_id: str = Form("exam_demo_001"),
    class_name: str = Form("未命名班级"),
    stage: str = Form("senior_high"),
    grade: str = Form("senior_high"),
) -> dict:
    paper_content, paper_meta = await _read_validated_upload(
        paper_file,
        allowed_suffixes={".json", ".docx"},
        default_suffix=".json",
        max_bytes=_configured_max_upload_bytes("CAMPUS_P2_MAX_PAPER_UPLOAD_BYTES", DEFAULT_MAX_PAPER_UPLOAD_BYTES),
        label="试卷文件",
    )
    score_content, score_meta = await _read_validated_upload(
        score_file,
        allowed_suffixes=SCORE_SUFFIXES,
        default_suffix=".xlsx",
        max_bytes=_configured_max_upload_bytes("CAMPUS_P2_MAX_SCORE_UPLOAD_BYTES", DEFAULT_MAX_SCORE_UPLOAD_BYTES),
        label="成绩表",
    )
    paper_suffix = paper_meta["suffix"]
    score_suffix = score_meta["suffix"]

    try:
        with TemporaryDirectory(prefix="campus_p2_") as temp_dir:
            base = Path(temp_dir)
            paper_path = base / f"paper{paper_suffix}"
            score_path = base / f"scores{score_suffix}"
            paper_path.write_bytes(paper_content)
            score_path.write_bytes(score_content)
            if paper_suffix == ".docx":
                job_id = f"p2_analyze_{uuid4().hex[:10]}"
                job_root = P1_PARSE_OUTPUT_ROOT / job_id
                _, summary = cut_docx_to_paper(
                    paper_path,
                    job_root,
                    provider="campus_p1_word_cutter_p2_analyze",
                    stage=_normalize_stage(stage),
                    grade=grade or _default_grade(stage),
                )
                paper_path = Path(summary.output_json)
                asset_base_url = f"/api/assets/data/p1_parse_outputs/{job_id}/{paper_path.parent.name}/assets"
            elif paper_suffix != ".json":
                raise ValueError("Please upload paper.v0.1 JSON or Word .docx for the paper file.")
            else:
                asset_base_url = ""
            analysis = analyze_exam(
                paper_json_path=paper_path,
                score_file_path=score_path,
                exam_id=exam_id,
                class_name=class_name,
            )
            if asset_base_url:
                analysis = _attach_asset_urls_to_analysis(analysis, asset_base_url)
            return _enrich_analysis(analysis).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


@app.post("/api/p2/reports/docx")
def export_p2_docx(analysis: P2ExamAnalysis) -> StreamingResponse:
    with TemporaryDirectory(prefix="campus_p2_report_") as temp_dir:
        output_path = Path(temp_dir) / "p2_report.docx"
        export_analysis_docx(analysis, output_path)
        output = BytesIO(output_path.read_bytes())
    filename = quote(f"{analysis.teaching_report.title}.docx")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.post("/api/p2/reports/markdown", response_class=PlainTextResponse)
def export_p2_markdown(analysis: P2ExamAnalysis) -> str:
    return analysis_to_markdown(analysis)


def _demo_readiness() -> dict:
    p3 = _p3_readiness()
    p1_paper_count = _count_p1_paper_outputs()
    customer_exams = [exam for exam in EXAMS.values() if not _is_system_test_exam(exam)]
    system_test_exams = [exam for exam in EXAMS.values() if _is_system_test_exam(exam)]
    p2_exam_count = len(customer_exams)
    p2_lesson_plan_count = sum(len(exam.get("lesson_plans", {})) for exam in customer_exams)
    p2_practice_pack_count = sum(len(exam.get("practice_packs", [])) for exam in customer_exams)
    system_test_exam_count = len(system_test_exams)
    system_test_lesson_plan_count = sum(len(exam.get("lesson_plans", {})) for exam in system_test_exams)
    system_test_practice_pack_count = sum(len(exam.get("practice_packs", [])) for exam in system_test_exams)
    p2_ready = p2_exam_count > 0 or bool((REPO_ROOT / "examples" / "normalized_paper_demo.json").exists())
    llm_configured = bool(os.getenv("CAMPUS_LLM_API_KEY"))
    security = _security_readiness()

    components = [
        {"key": "p1", "name": "P1 数据结构化", "status": "ready", "detail": "Word、成绩表、知识点、错题、引导和变式 demo 接口可用"},
        {
            "key": "p2",
            "name": "P2 教师诊断",
            "status": "ready" if p2_ready else "degraded",
            "detail": f"{p2_exam_count} 场客户考试，{p2_lesson_plan_count} 份教案，{p2_practice_pack_count} 个训练包",
        },
        {
            "key": "p3",
            "name": "P3 题库服务",
            "status": p3["status"],
            "detail": p3["detail"],
        },
        {
            "key": "llm",
            "name": "大模型能力",
            "status": "ready" if llm_configured else "fallback",
            "detail": "已配置环境变量" if llm_configured else "未配置 key，使用规则兜底",
        },
        {
            "key": "security",
            "name": "安全与审计",
            "status": "ready",
            "detail": security["detail"],
        },
    ]
    ready_count = sum(1 for item in components if item["status"] == "ready")
    overall_status = "ready" if ready_count >= 4 and p3["status"] == "ready" else "degraded"
    return {
        "overall_status": overall_status,
        "components": components,
        "facts": {
            "paper_count": p1_paper_count,
            "question_count": p3["question_count"],
            "knowledge_point_count": p3["knowledge_point_count"],
            "exam_count": p2_exam_count,
            "lesson_plan_count": p2_lesson_plan_count,
            "practice_pack_count": p2_practice_pack_count,
            "system_test_exam_count": system_test_exam_count,
            "system_test_lesson_plan_count": system_test_lesson_plan_count,
            "system_test_practice_pack_count": system_test_practice_pack_count,
        },
        "p3": {
            "configured": bool(p3["base_url"]),
            "connected": p3["status"] == "ready",
            "sample_search_count": p3["sample_search_count"],
        },
        "llm": {
            "enabled": llm_configured,
            "base_url_configured": bool(os.getenv("CAMPUS_LLM_BASE_URL")),
            "model": os.getenv("CAMPUS_LLM_MODEL", "openai-compatible"),
        },
        "security": security,
    }


def _p3_runtime_config() -> dict:
    return {
        "p3_base_url": os.getenv("CAMPUS_P3_BASE_URL", ""),
        "service_id": os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
        "auth_token": os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
        "timeout_seconds": float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    }


def _security_readiness() -> dict:
    auth_required = _env_flag("CAMPUS_AUTH_REQUIRED")
    token_configured = bool(os.getenv("CAMPUS_P2_AUTH_TOKEN", "").strip())
    directory = _identity_directory_summary()
    paper_limit = _configured_max_upload_bytes("CAMPUS_P2_MAX_PAPER_UPLOAD_BYTES", DEFAULT_MAX_PAPER_UPLOAD_BYTES)
    score_limit = _configured_max_upload_bytes("CAMPUS_P2_MAX_SCORE_UPLOAD_BYTES", DEFAULT_MAX_SCORE_UPLOAD_BYTES)
    auth_detail = "token 模式" if auth_required and token_configured else "身份请求头模式" if auth_required else "开放演示模式"
    return {
        "auth_required": auth_required,
        "token_configured": token_configured,
        "identity_directory_required": directory["required"],
        "identity_directory_configured": directory["configured"],
        "identity_directory_user_count": directory["user_count"],
        "default_tenant_id": os.getenv("CAMPUS_DEFAULT_TENANT_ID", "demo_school"),
        "file_hashing_enabled": True,
        "static_assets_scoped": True,
        "max_paper_upload_mb": round(paper_limit / 1024 / 1024, 1),
        "max_score_upload_mb": round(score_limit / 1024 / 1024, 1),
        "detail": (
            f"{auth_detail}；上传校验与 SHA-256 审计已启用，"
            f"账号目录 {directory['user_count']} 个用户；"
            f"试卷 {round(paper_limit / 1024 / 1024)}MB / 成绩 {round(score_limit / 1024 / 1024)}MB"
        ),
    }


def _generated_candidate_payload(item: GeneratedQuestionCandidateRequest) -> dict:
    knowledge_point_ids = [part for part in dict.fromkeys(item.knowledge_point_ids) if part]
    if not knowledge_point_ids:
        raise HTTPException(
            status_code=400,
            detail={"message": "knowledge_point_ids cannot be empty for generated question review"},
        )
    return {
        "generated_question_id": item.generated_question_id or f"genq_p2_{uuid4().hex[:12]}",
        "content_html": item.content_html,
        "answer_html": item.answer_html,
        "analysis_html": item.analysis_html,
        "knowledge_point_ids": knowledge_point_ids,
        "question_type": item.question_type or "solution",
        "difficulty": min(max(float(item.difficulty), 0.0), 1.0),
        "images": item.images,
        "validation": item.validation,
        "raw_response": item.raw_response,
    }


def _save_local_generated_questions(
    payload: SaveGeneratedQuestionsRequest,
    normalized_items: list[dict],
    fallback_reason: str,
) -> dict:
    now = STORE.now()
    response_items = []
    created_count = 0
    updated_count = 0
    for item in normalized_items:
        generated_question_id = item["generated_question_id"]
        status = "updated" if generated_question_id in LOCAL_GENERATED_QUESTIONS else "created"
        if status == "created":
            created_count += 1
        else:
            updated_count += 1
        LOCAL_GENERATED_QUESTIONS[generated_question_id] = {
            **item,
            "source_question_id": payload.source_question_id or None,
            "knowledge_point_version": payload.knowledge_point_version,
            "audit_status": "pending_review",
            "reviewer_id": None,
            "review_comment": "",
            "reviewed_at": None,
            "model_name": payload.model_name,
            "prompt_version": payload.prompt_version,
            "bank_question_id": None,
            "created_at": LOCAL_GENERATED_QUESTIONS.get(generated_question_id, {}).get("created_at", now),
            "updated_at": now,
            "fallback_reason": fallback_reason,
        }
        response_items.append(
            {
                "generated_question_id": generated_question_id,
                "status": status,
                "audit_status": "pending_review",
            }
        )
    return {
        "saved_count": created_count + updated_count,
        "created_count": created_count,
        "updated_count": updated_count,
        "audit_status": "pending_review",
        "items": response_items,
        "source": "local",
        "message": "P3 暂不可用，AI 生成题已进入 P2 本地待审队列。",
    }


def _local_generated_question_items(
    *,
    status: str,
    knowledge_point_version: str,
    knowledge_point_id: str,
    limit: int,
) -> list[dict]:
    items = []
    for item in LOCAL_GENERATED_QUESTIONS.values():
        if status and item.get("audit_status") != status:
            continue
        if knowledge_point_version and item.get("knowledge_point_version") != knowledge_point_version:
            continue
        if knowledge_point_id and knowledge_point_id not in item.get("knowledge_point_ids", []):
            continue
        items.append({key: value for key, value in item.items() if key != "fallback_reason"})
    items.sort(key=lambda value: value.get("created_at", ""), reverse=True)
    return items[: max(1, min(limit, 100))]


def _review_local_generated_question(
    generated_question_id: str,
    payload: ReviewGeneratedQuestionRequest,
    fallback_reason: str,
) -> dict:
    item = LOCAL_GENERATED_QUESTIONS.get(generated_question_id)
    if not item:
        raise HTTPException(
            status_code=404,
            detail={"message": f"AI 生成题未找到，P3 回退原因：{fallback_reason}"},
        )
    if item.get("audit_status") != "pending_review":
        raise HTTPException(status_code=409, detail={"message": "AI 生成题已经审核，不能重复提交"})
    now = STORE.now()
    item["audit_status"] = payload.decision
    item["reviewer_id"] = payload.reviewer_id
    item["review_comment"] = payload.review_comment
    item["reviewed_at"] = now
    item["updated_at"] = now
    item["bank_question_id"] = (
        f"bq_local_ai_{uuid4().hex[:10]}"
        if payload.decision == "approved" and payload.publish_to_bank
        else None
    )
    return {
        "generated_question_id": generated_question_id,
        "audit_status": item["audit_status"],
        "bank_question_id": item["bank_question_id"],
        "source": "local",
        "message": "P3 暂不可用，审核结果已保留在 P2 本地队列。",
    }


def _p3_student_get(path: str, *, student_id: str, tenant_id: str, params: dict) -> dict:
    p3_base_url = _p3_base_url_or_raise()
    response = httpx.get(
        f"{p3_base_url}{path}",
        params=params,
        headers=_p3_student_headers(student_id, tenant_id),
        timeout=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )
    response.raise_for_status()
    return _p3_envelope_data(response.json())


def _p3_student_post(
    path: str,
    *,
    student_id: str,
    tenant_id: str,
    payload: dict,
    idempotency_key: str = "",
) -> dict:
    p3_base_url = _p3_base_url_or_raise()
    headers = _p3_student_headers(student_id, tenant_id)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = httpx.post(
        f"{p3_base_url}{path}",
        json=payload,
        headers=headers,
        timeout=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )
    response.raise_for_status()
    return _p3_envelope_data(response.json())


def _p3_student_put(path: str, *, student_id: str, tenant_id: str, payload: dict) -> dict:
    p3_base_url = _p3_base_url_or_raise()
    response = httpx.put(
        f"{p3_base_url}{path}",
        json=payload,
        headers=_p3_student_headers(student_id, tenant_id),
        timeout=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )
    response.raise_for_status()
    return _p3_envelope_data(response.json())


def _p3_student_upload(
    path: str,
    *,
    student_id: str,
    tenant_id: str,
    data: dict,
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
    idempotency_key: str = "",
) -> dict:
    p3_base_url = _p3_base_url_or_raise()
    headers = _p3_student_headers(student_id, tenant_id)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = httpx.post(
        f"{p3_base_url}{path}",
        data=data,
        files={file_field: (file_name, file_bytes, content_type)},
        headers=headers,
        timeout=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )
    response.raise_for_status()
    return _p3_envelope_data(response.json())


def _p3_base_url_or_raise() -> str:
    p3_base_url = os.getenv("CAMPUS_P3_BASE_URL", "").rstrip("/")
    if not p3_base_url:
        raise RuntimeError("未配置 CAMPUS_P3_BASE_URL")
    return p3_base_url


def _p3_student_headers(student_id: str, tenant_id: str) -> dict[str, str]:
    headers = {"X-Student-Id": student_id, "X-Tenant-Id": tenant_id or "demo_school"}
    auth_token = os.getenv("CAMPUS_P3_AUTH_TOKEN", "")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def _p3_envelope_data(payload: dict) -> dict:
    if payload.get("code") != "OK":
        raise RuntimeError(payload.get("message") or "P3 response is not OK")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("P3 response data is invalid")
    return data


def _student_practice_fallback(limit: int) -> dict:
    analysis = _enrich_analysis(
        analyze_exam(
            paper_json_path=REPO_ROOT / "examples" / "normalized_paper_demo.json",
            score_file_path=REPO_ROOT / "examples" / "sample_exam_scores.xlsx",
            exam_id="student_fallback_demo",
            class_name="学生练习兜底",
        )
    )
    items = []
    for group in analysis.practice_recommendations or []:
        for recommendation in group.items:
            item = recommendation.model_dump()
            item.setdefault("knowledge_point_ids", [group.knowledge_point_id])
            item.setdefault("knowledge_point_version", "2026.1")
            item.setdefault("images", [])
            item.setdefault("recommend_reason", f"来自薄弱知识点：{group.knowledge_point_name}")
            items.append(item)
            if len(items) >= limit:
                return {"source": "local-fallback", "items": items}
    return {"source": "local-fallback", "items": items[:limit]}


def _p3_readiness() -> dict:
    p3_base_url = os.getenv("CAMPUS_P3_BASE_URL", "").rstrip("/")
    local_counts = _read_local_p3_counts()
    result = {
        "status": "not_configured",
        "base_url": p3_base_url,
        "detail": "未配置 P3 地址，推荐题会使用本地 fixture 回退",
        "knowledge_point_count": local_counts["knowledge_point_count"],
        "question_count": local_counts["question_count"],
        "sample_search_count": 0,
    }
    if not p3_base_url:
        return result

    headers = {"X-Service-Id": os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service")}
    auth_token = os.getenv("CAMPUS_P3_AUTH_TOKEN", "")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    timeout_seconds = float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5"))
    try:
        health_response = httpx.get(f"{p3_base_url}/api/health/", timeout=timeout_seconds)
        health_response.raise_for_status()
        stats_response = httpx.get(
            f"{p3_base_url}/api/resource/v1/stats",
            params={"version": "2026.1"},
            headers=headers,
            timeout=timeout_seconds,
        )
        stats_response.raise_for_status()
        stats_payload = stats_response.json()
        if stats_payload.get("code") == "OK":
            stats_data = stats_payload.get("data", {})
            result["knowledge_point_count"] = int(stats_data.get("knowledge_point_count") or 0)
            result["question_count"] = int(
                stats_data.get("approved_question_count")
                or stats_data.get("question_count")
                or 0
            )
        knowledge_response = httpx.get(
            f"{p3_base_url}/api/resource/v1/knowledge-points",
            params={"subject": "math", "version": "2026.1", "enabled": "true"},
            headers=headers,
            timeout=timeout_seconds,
        )
        knowledge_response.raise_for_status()
        knowledge_payload = knowledge_response.json()
        if knowledge_payload.get("code") == "OK" and not result["knowledge_point_count"]:
            result["knowledge_point_count"] = len(knowledge_payload.get("data", {}).get("items", []))

        search_response = httpx.post(
            f"{p3_base_url}/api/resource/v1/questions/search",
            headers=headers,
            json={
                "knowledge_point_ids": ["kp_math_junior_statistics"],
                "knowledge_point_version": "2026.1",
                "difficulty_range": [0.2, 0.9],
                "limit": 5,
            },
            timeout=timeout_seconds,
        )
        search_response.raise_for_status()
        search_payload = search_response.json()
        if search_payload.get("code") == "OK":
            result["sample_search_count"] = len(search_payload.get("data", {}).get("items", []))
        result["status"] = "ready"
        result["detail"] = f"HTTP 已连接，抽样返回 {result['sample_search_count']} 道推荐题"
    except Exception as exc:
        result["status"] = "degraded"
        result["detail"] = f"P3 HTTP 暂不可用，已保留本地回退：{exc}"
    return result


def _read_local_p3_counts() -> dict:
    db_path = Path(os.getenv("P3_SQLITE_PATH", str(DATA_ROOT / "p3_demo.sqlite3")))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    counts = {"knowledge_point_count": 0, "question_count": 0}
    if not db_path.exists() or db_path.stat().st_size == 0:
        return counts
    try:
        with sqlite3.connect(db_path) as conn:
            counts["knowledge_point_count"] = int(conn.execute("SELECT COUNT(*) FROM resources_knowledgepoint").fetchone()[0])
            counts["question_count"] = int(conn.execute("SELECT COUNT(*) FROM resources_questionbankitem").fetchone()[0])
    except Exception:
        return {"knowledge_point_count": 0, "question_count": 0}
    return counts


def _count_p1_paper_outputs() -> int:
    paper_root = REPO_ROOT / "campus_p1" / "web_app" / "backend" / "papers"
    if not paper_root.exists():
        return 0
    return sum(1 for path in paper_root.glob("*/paper.json") if path.is_file())


def _exam_summary(exam: dict) -> dict:
    structure = exam.get("structure") or {}
    exam_id = exam["exam_id"]
    diagnostics = [
        diagnostic_id
        for diagnostic_id, diagnostic in DIAGNOSTICS.items()
        if diagnostic.get("exam_id") == exam_id
    ]
    lesson_plans = [_lesson_plan_summary(lesson_plan) for lesson_plan in exam.get("lesson_plans", {}).values()]
    lesson_plans.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    practice_packs = list(exam.get("practice_packs", []))
    practice_packs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {
        "exam_id": exam_id,
        "status": exam.get("status", "draft"),
        "name": exam.get("payload", {}).get("name", ""),
        "subject": exam.get("payload", {}).get("subject", "math"),
        "grade": exam.get("payload", {}).get("grade", ""),
        "class_ids": exam.get("payload", {}).get("class_ids", []),
        "exam_date": exam.get("payload", {}).get("exam_date", ""),
        "teacher_id": exam.get("payload", {}).get("teacher_id", ""),
        "tenant_id": exam.get("payload", {}).get("tenant_id", ""),
        "is_system_test": _is_system_test_exam(exam),
        "file_types": sorted(exam.get("files", {}).keys()),
        "question_count": len(structure.get("questions", [])),
        "warning_count": len(exam.get("warnings", [])),
        "diagnostic_ids": diagnostics,
        "lesson_plan_count": len(lesson_plans),
        "latest_lesson_plan": lesson_plans[0] if lesson_plans else None,
        "practice_pack_count": len(practice_packs),
        "latest_practice_pack": practice_packs[0] if practice_packs else None,
        "created_at": exam.get("created_at", ""),
        "updated_at": exam.get("updated_at", ""),
    }


def _is_system_test_exam(exam: dict) -> bool:
    payload = exam.get("payload", {}) or {}
    if payload.get("is_system_test") is True:
        return True
    class_ids = payload.get("class_ids", [])
    if isinstance(class_ids, str):
        class_ids_text = class_ids
    else:
        class_ids_text = ",".join(str(item) for item in class_ids if item)
    values = [
        exam.get("exam_id", ""),
        payload.get("name", ""),
        payload.get("teacher_id", ""),
        class_ids_text,
    ]
    text = " ".join(str(value).lower() for value in values)
    markers = [
        "smoke",
        "http teacher",
        "word paper standard flow",
        "full-stack http",
        "demo math exam",
        "full-stack verification",
        "frontend-standard-flow",
        "standard-flow-live",
        "p2_smoke",
        "teacher_http_smoke",
        "teacher_smoke",
    ]
    return any(marker in text for marker in markers)


def _lesson_plan_summary(lesson_plan: dict) -> dict:
    file_payload = lesson_plan.get("file", {})
    return {
        "lesson_plan_id": lesson_plan.get("lesson_plan_id", ""),
        "diagnostic_id": lesson_plan.get("diagnostic_id", ""),
        "file_name": file_payload.get("file_name", ""),
        "download_url": file_payload.get("download_url", ""),
        "size_bytes": file_payload.get("size_bytes", 0),
        "created_at": lesson_plan.get("created_at", ""),
    }


def _suffix_or_default(filename: str | None, default: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix or default


async def _read_validated_upload(
    file: UploadFile,
    *,
    allowed_suffixes: set[str],
    default_suffix: str,
    max_bytes: int,
    label: str,
) -> tuple[bytes, dict]:
    file_name = Path(file.filename or f"upload{default_suffix}").name
    suffix = _suffix_or_default(file_name, default_suffix)
    if suffix not in allowed_suffixes:
        allowed = "、".join(sorted(allowed_suffixes))
        raise HTTPException(status_code=400, detail={"message": f"{label}仅支持 {allowed} 文件"})

    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        limit_mb = max_bytes / 1024 / 1024
        raise HTTPException(status_code=413, detail={"message": f"{label}不能超过 {limit_mb:.0f}MB"})
    if not content:
        raise HTTPException(status_code=400, detail={"message": f"{label}不能为空"})

    return content, {
        "file_name": file_name,
        "suffix": suffix,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _configured_max_upload_bytes(env_name: str, default: int) -> int:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _normalize_stage(stage: str) -> str:
    normalized = (stage or "").strip().lower()
    if normalized in {"junior_high", "junior", "middle", "初中", "初三"}:
        return "junior_high"
    return "senior_high"


def _default_grade(stage: str) -> str:
    return "初三" if _normalize_stage(stage) == "junior_high" else "高三"


def _stage_from_exam_payload(payload: dict) -> str:
    grade = str(payload.get("grade") or "")
    subject_stage = str(payload.get("stage") or "")
    text = f"{grade} {subject_stage}".lower()
    if "junior" in text or "middle" in text or "初" in text or "中考" in text:
        return "junior_high"
    return "senior_high"


def _class_name_from_exam(exam: dict) -> str:
    payload = exam.get("payload", {})
    class_ids = payload.get("class_ids") or []
    if class_ids:
        return str(class_ids[0])
    return payload.get("name") or "Demo class"


def _sync_analysis_question(exam: dict, exam_question_id: str, update: dict, mark_confirmed: bool = True) -> None:
    analysis: P2ExamAnalysis | None = exam.get("analysis")
    if analysis is None:
        return
    structure = exam.get("structure") or {}
    structure_question = next(
        (
            question
            for question in structure.get("questions", [])
            if question.get("exam_question_id") == exam_question_id
        ),
        {},
    )
    for index, item in enumerate(analysis.question_analysis, 1):
        item_id = item.question_id or f"eq_{index:03d}"
        if item_id != exam_question_id:
            continue
        if "question_no" in update:
            item.question_no = update["question_no"]
        if "stem_text" in update and update["stem_text"] is not None:
            item.stem_text = str(update["stem_text"])
            if hasattr(item, "stem_markdown"):
                item.stem_markdown = str(update["stem_text"])
        elif "stem_html" in update:
            item.stem_text = _plain_text_from_html(update["stem_html"])
            if hasattr(item, "stem_markdown") and not getattr(item, "stem_markdown", ""):
                item.stem_markdown = item.stem_text
        if "question_type" in update:
            item.question_type = update["question_type"]
        if "full_score" in update and update["full_score"] is not None:
            item.full_score = float(update["full_score"])
        if "options" in update and update["options"] is not None:
            item.options = [option for option in update["options"] if isinstance(option, dict)]
        if "images" in update and update["images"] is not None:
            item.images = _normalize_question_images(update["images"])
        if "knowledge_point_ids" in update:
            item.confirmed_knowledge_points = _knowledge_refs_from_ids(
                item.confirmed_knowledge_points,
                update["knowledge_point_ids"],
                structure_question,
            )
        if update:
            if mark_confirmed:
                item.teacher_review_status = "confirmed"
            item.score_rate = round(min(max(item.avg_score / item.full_score, 0), 1), 4) if item.full_score else 0
            item.loss_rate = round(1 - item.score_rate, 4)
            item.severity = _severity_for_score_rate(item.score_rate)
        break


def _refresh_analysis_from_structure(exam: dict) -> P2ExamAnalysis:
    analysis: P2ExamAnalysis = exam["analysis"].model_copy(deep=True)
    shadow_exam = {**exam, "analysis": analysis}
    for question in (exam.get("structure") or {}).get("questions", []):
        _sync_analysis_question(
            shadow_exam,
            question["exam_question_id"],
            {
                "question_no": question.get("question_no"),
                "stem_text": question.get("stem_text") or question.get("stem_markdown") or _plain_text_from_html(question.get("stem_html", "")),
                "stem_html": question.get("stem_html", ""),
                "question_type": question.get("question_type"),
                "full_score": question.get("full_score"),
                "options": question.get("options", []),
                "images": question.get("images", []),
                "knowledge_point_ids": question.get("knowledge_point_ids", []),
            },
            mark_confirmed=False,
        )

    buckets: dict[str, dict] = {}
    for item in analysis.question_analysis:
        for point in item.confirmed_knowledge_points:
            code = point.get("code") or point.get("knowledge_point_id") or point.get("id")
            if not code:
                continue
            bucket = buckets.setdefault(
                code,
                {"name": point.get("name") or code, "full": 0.0, "avg": 0.0, "question_nos": []},
            )
            bucket["full"] += item.full_score
            bucket["avg"] += item.avg_score
            bucket["question_nos"].append(item.question_no)

    diagnostics: list[KnowledgeDiagnostic] = []
    for code, bucket in buckets.items():
        score_rate = round(min(max(bucket["avg"] / bucket["full"], 0), 1), 4) if bucket["full"] else 0
        severity = _severity_for_score_rate(score_rate)
        diagnostics.append(
            KnowledgeDiagnostic(
                code=code,
                name=bucket["name"],
                score_rate=score_rate,
                loss_rate=round(1 - score_rate, 4),
                severity=severity,
                related_question_nos=bucket["question_nos"],
                suggestion=_diagnostic_suggestion(bucket["name"], severity),
            )
        )
    diagnostics.sort(key=lambda item: item.score_rate)
    analysis.knowledge_diagnostics = diagnostics

    weak_diagnostics = [item for item in diagnostics if item.severity != "stable"][:8]
    analysis.p3_search_requests = [
        P3SearchRequest(
            knowledge_point_codes=[item.code],
            knowledge_point_ids=[item.code],
            question_type=None,
            difficulty_range=(0.35, 0.75),
            limit=5,
            exclude_question_ids=[
                question.question_id
                for question in analysis.question_analysis
                if question.question_id
                and any((point.get("code") or point.get("knowledge_point_id")) == item.code for point in question.confirmed_knowledge_points)
            ],
        )
        for item in weak_diagnostics
    ]

    total_full = sum(item.full_score for item in analysis.question_analysis)
    total_avg = sum(item.avg_score for item in analysis.question_analysis)
    avg_rate = round(total_avg / total_full, 4) if total_full else 0
    tagged_questions = sum(1 for item in analysis.question_analysis if item.confirmed_knowledge_points)
    analysis.knowledge_tag_coverage = (
        round(tagged_questions / len(analysis.question_analysis), 4) if analysis.question_analysis else 0
    )
    priority = sorted(analysis.question_analysis, key=lambda item: item.score_rate)[:6]
    weak_names = [item.name for item in weak_diagnostics if item.severity in {"critical", "weak"}]
    analysis.teaching_report.summary = (
        f"本次分析匹配 {len(analysis.question_analysis)} 道题，整体得分率 {round(avg_rate * 100, 1)}%，"
        f"知识点覆盖率 {round(analysis.knowledge_tag_coverage * 100, 1)}%。"
    )
    analysis.teaching_report.priority_question_nos = [item.question_no for item in priority]
    analysis.teaching_report.weak_knowledge_points = weak_names
    analysis.teaching_report.markdown = _teaching_report_summary_markdown(analysis, avg_rate, priority, weak_diagnostics)
    return attach_practice_recommendations(
        analysis,
        p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
        service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
        auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
        timeout_seconds=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )


def _teaching_report_summary_markdown(
    analysis: P2ExamAnalysis,
    avg_rate: float,
    priority: list[QuestionAnalysis],
    weak_diagnostics: list[KnowledgeDiagnostic],
) -> str:
    lines = [
        f"# {analysis.teaching_report.title}",
        "",
        f"班级：{analysis.class_name}",
        f"整体得分率：{avg_rate:.1%}",
        f"知识点覆盖率：{analysis.knowledge_tag_coverage:.1%}",
        "",
        "## 优先讲评题",
    ]
    for item in priority:
        kp_names = knowledge_names(item.confirmed_knowledge_points)
        lines.append(f"- {item.question_no}：得分率 {item.score_rate:.1%}，知识点：{kp_names}")

    lines.extend(["", "## 薄弱知识点"])
    for item in weak_diagnostics[:6]:
        lines.append(f"- {item.name}：得分率 {item.score_rate:.1%}，涉及题号 {', '.join(item.related_question_nos)}。{item.suggestion}")

    return "\n".join(lines)


def _normalize_question_images(images: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for index, raw in enumerate(images, 1):
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or raw.get("url") or "").strip()
        image_id = str(raw.get("image_id") or raw.get("id") or f"img_{index:02d}").strip()
        role = str(raw.get("role") or "stem").strip() or "stem"
        if not path:
            continue
        normalized.append({"image_id": image_id or f"img_{index:02d}", "path": path, "role": role})
    return normalized


def _attach_asset_urls_to_analysis(analysis: P2ExamAnalysis, asset_base_url: str) -> P2ExamAnalysis:
    normalized_base = asset_base_url.rstrip("/")
    if not normalized_base:
        return analysis
    for question in analysis.question_analysis:
        resolved_images: list[dict] = []
        for image in question.images:
            item = dict(image)
            path = str(item.get("path") or "").strip()
            if path and not path.startswith(("http://", "https://", "/api/")):
                filename = path.split("/")[-1]
                item["path"] = f"{normalized_base}/{quote(filename)}"
            resolved_images.append(item)
        question.images = resolved_images
    return analysis


def _knowledge_refs_from_ids(existing: list[dict], ids: list[str], structure_question: dict) -> list[dict]:
    lookup: dict[str, dict] = {}
    for point in existing + structure_question.get("knowledge_candidates", []):
        for key in ("code", "knowledge_point_id", "id", "name"):
            value = point.get(key)
            if value:
                lookup[str(value)] = point
    refs = []
    for kp_id in ids:
        point = lookup.get(kp_id, {})
        source = point.get("source") or "teacher"
        refs.append(
            {
                "code": point.get("code") or point.get("knowledge_point_id") or kp_id,
                "name": point.get("name") or point.get("knowledge_point_name") or kp_id,
                "confidence": point.get("confidence", 1.0 if source == "teacher" else 0.8),
                "source": source,
            }
        )
    return refs


def _severity_for_score_rate(score_rate: float) -> str:
    if score_rate < 0.45:
        return "critical"
    if score_rate < 0.6:
        return "weak"
    if score_rate < 0.75:
        return "watch"
    return "stable"


def _diagnostic_suggestion(name: str, severity: str) -> str:
    if severity == "critical":
        return f"建议优先重建“{name}”的基础模型，并安排同类基础题回炉。"
    if severity == "weak":
        return f"建议围绕“{name}”安排分层训练，先巩固再迁移。"
    if severity == "watch":
        return f"建议用 1 到 2 道变式题确认“{name}”是否真正掌握。"
    return f"“{name}”整体较稳定，可作为综合题中的辅助知识点。"


def _plain_text_from_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _exam_or_404(exam_id: str, actor: ActorContext | None = None) -> dict:
    if actor is not None:
        _require_teacher_workspace(actor, "访问教师端考试")
    exam = EXAMS.get(exam_id)
    if exam is None or (actor is not None and not _actor_can_access_exam(exam, actor)):
        raise HTTPException(status_code=404, detail={"message": "考试不存在"})
    return exam


def _actor_can_access_exam(exam: dict, actor: ActorContext) -> bool:
    if not actor.auth_required:
        return True
    exam_tenant_id = str(exam.get("payload", {}).get("tenant_id", "")).strip()
    if not exam_tenant_id:
        return True
    return exam_tenant_id == actor.tenant_id


def _file_or_404(file_id: str, exam_id: str) -> dict:
    file_record = FILES.get(file_id)
    if file_record is None or file_record["exam_id"] != exam_id:
        raise HTTPException(status_code=404, detail={"message": "文件不存在"})
    return file_record


def _analyze_uploaded_pair(paper: dict, score: dict, exam_id: str, exam: dict) -> P2ExamAnalysis:
    paper_suffix = Path(paper["metadata"]["file_name"]).suffix.lower()
    score_suffix = Path(score["metadata"]["file_name"]).suffix.lower() or ".xlsx"
    if paper_suffix not in {".json", ".docx"}:
        raise ValueError(
            "The integrated demo can parse paper.v0.1 JSON or Word .docx. "
            "PDF/image parsing remains a P1 roadmap item."
        )

    with TemporaryDirectory(prefix="campus_p2_standard_") as temp_dir:
        base = Path(temp_dir)
        score_path = base / f"scores{score_suffix}"
        score_path.write_bytes(score["content"])
        if paper_suffix == ".json":
            paper_path = base / "paper.json"
            paper_path.write_bytes(paper["content"])
        else:
            paper_docx_path = base / "paper.docx"
            paper_docx_path.write_bytes(paper["content"])
            stage = _stage_from_exam_payload(exam.get("payload", {}))
            job_id = f"p2_standard_{exam_id}_{uuid4().hex[:8]}"
            job_root = P1_PARSE_OUTPUT_ROOT / job_id
            paper_payload, summary = cut_docx_to_paper(
                paper_docx_path,
                job_root,
                provider="campus_p1_word_cutter_standard_flow",
                stage=stage,
                grade=exam.get("payload", {}).get("grade") or _default_grade(stage),
            )
            paper_path = Path(summary.output_json)
            asset_base_url = f"/api/assets/data/p1_parse_outputs/{job_id}/{paper_payload.get('paper_id', paper_path.parent.name)}/assets"
            exam["p1_parse"] = {
                "paper_id": paper_payload.get("paper_id", ""),
                "summary": asdict(summary),
                "paper_url": f"/api/assets/data/p1_parse_outputs/{job_id}/{paper_payload.get('paper_id', paper_path.parent.name)}/paper.json",
                "asset_base_url": asset_base_url,
            }
        analysis = analyze_exam(
            paper_json_path=paper_path,
            score_file_path=score_path,
            exam_id=exam_id,
            class_name=_class_name_from_exam(exam),
        )
        if paper_suffix == ".docx":
            analysis = _attach_asset_urls_to_analysis(analysis, asset_base_url)
        return analysis


def _analysis_to_structure(exam_id: str, analysis: P2ExamAnalysis) -> dict:
    questions = []
    for index, item in enumerate(analysis.question_analysis, 1):
        exam_question_id = item.question_id or f"eq_{index:03d}"
        questions.append(
            {
                "exam_question_id": exam_question_id,
                "question_no": item.question_no,
                "full_score": item.full_score,
                "avg_score": item.avg_score,
                "score_rate": item.score_rate,
                "question_type": item.question_type or "",
                "stem_text": item.stem_text,
                "stem_markdown": getattr(item, "stem_markdown", "") or item.stem_text,
                "stem_html": f"<p>{item.stem_text}</p>" if item.stem_text else "",
                "options": item.options,
                "images": item.images,
                "parse_confidence": item.parse_confidence,
                "knowledge_candidates": item.confirmed_knowledge_points,
                "knowledge_point_ids": [kp["code"] for kp in item.confirmed_knowledge_points],
                "needs_review": bool(item.needs_review or item.warnings),
            }
        )
    return {
        "exam_id": exam_id,
        "status": "teacher_review",
        "questions": questions,
        "warnings": analysis.warnings,
    }


def _analysis_to_diagnostic(diagnostic_id: str, analysis: P2ExamAnalysis) -> dict:
    high_loss = [
        {
            "question_no": item.question_no,
            "loss_rate": item.loss_rate,
            "reason": knowledge_names(item.confirmed_knowledge_points),
        }
        for item in analysis.question_analysis
        if item.severity in {"critical", "weak"}
    ][:8]
    weakness = [
        {
            "knowledge_point_id": item.code,
            "knowledge_point_name": item.name,
            "mastery_rate": item.score_rate,
            "severity": "high" if item.severity == "critical" else item.severity,
            "related_question_nos": item.related_question_nos,
            "avg_loss_rate": item.loss_rate,
            "suggestion": item.suggestion,
        }
        for item in analysis.knowledge_diagnostics
        if item.severity != "stable"
    ]
    total_full = sum(item.full_score for item in analysis.question_analysis)
    total_avg = sum(item.avg_score for item in analysis.question_analysis)
    tagged = sum(1 for item in analysis.question_analysis if item.confirmed_knowledge_points)
    question_count = len(analysis.question_analysis)
    return {
        "diagnostic_id": diagnostic_id,
        "exam_id": analysis.exam_id,
        "summary": {
            "question_count": question_count,
            "avg_score_rate": round(total_avg / total_full, 4) if total_full else 0,
            "knowledge_tag_coverage": round(tagged / question_count, 4) if question_count else 0,
        },
        "weakness_items": weakness,
        "high_loss_questions": high_loss,
        "practice_pack_ids": ["pack_demo_001"] if weakness else [],
    }


def knowledge_names(points: list[dict]) -> str:
    return "、".join(point.get("name", "") for point in points if point.get("name")) or "待教师确认"


def _enrich_analysis(analysis: P2ExamAnalysis, *, use_model_tags: bool | None = None) -> P2ExamAnalysis:
    _apply_fast_knowledge_tags(analysis)
    if use_model_tags is None:
        use_model_tags = os.getenv("CAMPUS_LLM_SYNC_TAGGING", "0").strip().lower() in {"1", "true", "yes", "on"}
    if use_model_tags:
        _apply_model_knowledge_tags(analysis)
    _refresh_analysis_computed_fields(analysis)
    return attach_practice_recommendations(
        analysis,
        p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
        service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
        auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
        timeout_seconds=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
    )


def _run_ai_knowledge_tag_job(job_id: str, exam_id: str, scope: str = "all") -> None:
    job = AI_KNOWLEDGE_TAG_JOBS.get(job_id)
    if not job:
        return
    job.update({"status": "running", "message": "正在用大模型校准知识点", "updated_at": STORE.now()})
    try:
        exam = EXAMS.get(exam_id)
        if exam is None or exam.get("analysis") is None:
            raise ValueError("考试分析不存在")
        analysis = _refresh_analysis_from_structure(exam) if exam.get("structure") else exam["analysis"].model_copy(deep=True)
        _apply_fast_knowledge_tags(analysis)
        updated_count = _apply_model_knowledge_tags(analysis)
        _refresh_analysis_computed_fields(analysis)
        analysis = attach_practice_recommendations(
            analysis,
            p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
            service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
            auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
            timeout_seconds=float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")),
        )
        exam["analysis"] = analysis
        exam["structure"] = _analysis_to_structure(exam_id, analysis)
        STORE.save_exam(exam)
        STORE.record_event(
            "ai_knowledge_tag_succeeded",
            "exam",
            exam_id,
            {"job_id": job_id, "scope": scope, "updated_count": updated_count},
        )
        job.update(
            {
                "status": "succeeded",
                "message": f"智能校准完成，更新 {updated_count} 道题",
                "updated_count": updated_count,
                "total_count": len(analysis.question_analysis),
                "updated_at": STORE.now(),
                "completed_at": STORE.now(),
                "error": None,
            }
        )
    except Exception as exc:
        job.update(
            {
                "status": "failed",
                "message": "智能校准失败",
                "updated_at": STORE.now(),
                "completed_at": STORE.now(),
                "error": str(exc),
            }
        )
        STORE.record_event(
            "ai_knowledge_tag_failed",
            "exam",
            exam_id,
            {"job_id": job_id, "scope": scope, "error": str(exc)[:240]},
        )


def _apply_fast_knowledge_tags(analysis: P2ExamAnalysis) -> None:
    if not analysis.question_analysis:
        return
    try:
        result = tag_knowledge_questions(
            _knowledge_tagging_payload(analysis),
            p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
            service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
            auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
            llm_base_url="",
            llm_api_key="",
            llm_model="heuristic-p3-2026.1",
            timeout_seconds=min(float(os.getenv("CAMPUS_P3_TIMEOUT_SECONDS", "5")), 3.0),
        )
    except Exception:
        return
    _apply_knowledge_tagging_result(analysis, result, only_empty=True)


def _apply_model_knowledge_tags(analysis: P2ExamAnalysis) -> int:
    llm_api_key = os.getenv("CAMPUS_LLM_API_KEY", "").strip()
    llm_base_url = os.getenv("CAMPUS_LLM_BASE_URL", "").strip()
    if not llm_api_key or not llm_base_url or not analysis.question_analysis:
        return 0

    try:
        result = tag_knowledge_questions(
            _knowledge_tagging_payload(analysis),
            p3_base_url=os.getenv("CAMPUS_P3_BASE_URL", ""),
            service_id=os.getenv("CAMPUS_P3_SERVICE_ID", "p2-service"),
            auth_token=os.getenv("CAMPUS_P3_AUTH_TOKEN", ""),
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=os.getenv("CAMPUS_LLM_MODEL", "openai-compatible"),
            timeout_seconds=float(os.getenv("CAMPUS_LLM_TIMEOUT_SECONDS", "8")),
        )
    except Exception:
        return 0

    return _apply_knowledge_tagging_result(analysis, result, only_empty=False, required_source="llm")


def _knowledge_tagging_payload(analysis: P2ExamAnalysis) -> dict:
    return {
        "subject": "math",
        "grade": "",
        "knowledge_version": "2026.1",
        "candidate_limit": 3,
        "questions": [
            {
                "question_no": item.question_no,
                "stem_text": item.stem_text,
                "stem_html": f"<p>{item.stem_text}</p>" if item.stem_text else "",
                "question_type": item.question_type or "",
                "options": item.options,
                "images": item.images,
            }
            for item in analysis.question_analysis
        ],
    }


def _apply_knowledge_tagging_result(
    analysis: P2ExamAnalysis,
    result: dict,
    *,
    only_empty: bool,
    required_source: str | None = None,
) -> int:
    by_no = {str(item.get("question_no", "")): item for item in result.get("items", []) if isinstance(item, dict)}
    updated_count = 0
    for item in analysis.question_analysis:
        if only_empty and item.confirmed_knowledge_points:
            continue
        tagged = by_no.get(item.question_no)
        if not tagged:
            continue
        if required_source and tagged.get("source") != required_source:
            continue
        candidates = _candidate_refs_from_tagged(tagged)
        if candidates:
            item.confirmed_knowledge_points = candidates[:3]
            updated_count += 1
    return updated_count


def _candidate_refs_from_tagged(tagged: dict) -> list[dict]:
    source = str(tagged.get("source") or "heuristic")
    candidates = []
    for raw in tagged.get("candidates") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("knowledge_point_name") or raw.get("code") or raw.get("knowledge_point_id") or "")
        code = str(raw.get("code") or raw.get("knowledge_point_id") or name)
        if not code:
            continue
        candidates.append(
            {
                "code": code,
                "name": name or code,
                "confidence": raw.get("confidence", 0.62 if source == "heuristic" else 0.8),
                "source": source,
                "reason": raw.get("reason", ""),
            }
        )
    return candidates


def _refresh_analysis_computed_fields(analysis: P2ExamAnalysis) -> None:
    buckets: dict[str, dict] = {}
    for item in analysis.question_analysis:
        for point in item.confirmed_knowledge_points:
            code = point.get("code") or point.get("knowledge_point_id") or point.get("id")
            if not code:
                continue
            bucket = buckets.setdefault(
                code,
                {"name": point.get("name") or code, "full": 0.0, "avg": 0.0, "question_nos": []},
            )
            bucket["full"] += item.full_score
            bucket["avg"] += item.avg_score
            bucket["question_nos"].append(item.question_no)

    diagnostics: list[KnowledgeDiagnostic] = []
    for code, bucket in buckets.items():
        score_rate = round(min(max(bucket["avg"] / bucket["full"], 0), 1), 4) if bucket["full"] else 0
        severity = _severity_for_score_rate(score_rate)
        diagnostics.append(
            KnowledgeDiagnostic(
                code=code,
                name=bucket["name"],
                score_rate=score_rate,
                loss_rate=round(1 - score_rate, 4),
                severity=severity,
                related_question_nos=bucket["question_nos"],
                suggestion=_diagnostic_suggestion(bucket["name"], severity),
            )
        )
    diagnostics.sort(key=lambda item: item.score_rate)
    analysis.knowledge_diagnostics = diagnostics
    weak_diagnostics = [item for item in diagnostics if item.severity != "stable"][:8]
    analysis.p3_search_requests = [
        P3SearchRequest(
            knowledge_point_codes=[item.code],
            knowledge_point_ids=[item.code],
            question_type=None,
            difficulty_range=(0.35, 0.75),
            limit=5,
            exclude_question_ids=[
                question.question_id
                for question in analysis.question_analysis
                if question.question_id
                and any((point.get("code") or point.get("knowledge_point_id")) == item.code for point in question.confirmed_knowledge_points)
            ],
        )
        for item in weak_diagnostics
    ]
    tagged_questions = sum(1 for item in analysis.question_analysis if item.confirmed_knowledge_points)
    analysis.knowledge_tag_coverage = (
        round(tagged_questions / len(analysis.question_analysis), 4) if analysis.question_analysis else 0
    )
    total_full = sum(item.full_score for item in analysis.question_analysis)
    total_avg = sum(item.avg_score for item in analysis.question_analysis)
    avg_rate = round(total_avg / total_full, 4) if total_full else 0
    priority = sorted(analysis.question_analysis, key=lambda item: item.score_rate)[:6]
    analysis.teaching_report.summary = (
        f"本次分析匹配 {len(analysis.question_analysis)} 道题，整体得分率 {round(avg_rate * 100, 1)}%，"
        f"知识点覆盖率 {round(analysis.knowledge_tag_coverage * 100, 1)}%。"
    )
    analysis.teaching_report.priority_question_nos = [item.question_no for item in priority]
    analysis.teaching_report.weak_knowledge_points = [
        item.name for item in weak_diagnostics if item.severity in {"critical", "weak"}
    ]
    analysis.teaching_report.markdown = _teaching_report_summary_markdown(analysis, avg_rate, priority, weak_diagnostics)
