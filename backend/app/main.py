from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from campus_p2_core.contracts.p2 import P2ExamAnalysis
from campus_p2_core.p2_teacher.analyzer import analyze_exam
from campus_p2_core.p2_teacher.report_exporter import analysis_to_markdown, export_analysis_docx


app = FastAPI(title="campus-system-p2 API", version="1.0.0")

EXAMS: dict[str, dict] = {}
FILES: dict[str, dict] = {}
DIAGNOSTICS: dict[str, dict] = {}

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


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "app": "campus-system-p2",
        "contract": "paper.v0.1 + p2.v0.1",
    }


class CreateExamRequest(BaseModel):
    name: str
    subject: str = "math"
    grade: str = ""
    class_ids: list[str] = Field(default_factory=list)
    exam_date: str = ""
    teacher_id: str = ""


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
    stem_html: str | None = None
    question_type: str | None = None
    full_score: float | None = None


class KnowledgeTagsRequest(BaseModel):
    knowledge_point_ids: list[str] = Field(default_factory=list)
    comment: str = ""


class LessonPlanRequest(BaseModel):
    diagnostic_id: str
    template_id: str = "tpl_school_math_review_v1"
    sections: list[str] = Field(default_factory=list)


def ok(data: dict, message: str = "success") -> dict:
    return {
        "request_id": f"req_{uuid4().hex[:12]}",
        "code": "OK",
        "message": message,
        "data": data,
    }


@app.post("/exams")
def create_exam(payload: CreateExamRequest) -> dict:
    exam_id = f"exam_{uuid4().hex[:8]}"
    EXAMS[exam_id] = {
        "exam_id": exam_id,
        "status": "draft",
        "payload": payload.model_dump(),
        "files": {},
        "analysis": None,
        "structure": None,
        "warnings": [],
    }
    return ok({"exam_id": exam_id, "status": "draft"})


@app.post("/exams/{exam_id}/files")
async def upload_exam_file(
    exam_id: str,
    file_type: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    exam = _exam_or_404(exam_id)
    if file_type not in {"score_excel", "paper"}:
        raise HTTPException(status_code=400, detail={"message": "file_type 必须为 score_excel 或 paper"})

    content = await file.read()
    file_id = f"file_{uuid4().hex[:10]}"
    metadata = {
        "file_id": file_id,
        "file_name": file.filename or f"{file_type}.bin",
        "mime_type": file.content_type or "application/octet-stream",
        "size_bytes": len(content),
        "storage_uri": f"local://exams/{exam_id}/{file_id}",
        "sha256": "",
    }
    FILES[file_id] = {
        "exam_id": exam_id,
        "file_type": file_type,
        "metadata": metadata,
        "content": content,
    }
    exam["files"][file_type] = file_id
    return ok({"file": metadata})


@app.post("/exams/{exam_id}/parse")
def parse_exam(exam_id: str, payload: ParseExamRequest) -> dict:
    exam = _exam_or_404(exam_id)
    score = _file_or_404(payload.score_file_id, exam_id)
    paper = _file_or_404(payload.paper_file_id, exam_id)

    jobs = [
        {"job_id": f"job_score_{uuid4().hex[:8]}", "job_type": "score_excel_parse"},
        {"job_id": f"job_paper_{uuid4().hex[:8]}", "job_type": "paper_parse"},
    ]
    exam["jobs"] = jobs
    exam["status"] = "parsing"

    try:
        analysis = _analyze_uploaded_pair(paper, score, exam_id)
    except ValueError as exc:
        exam["status"] = "needs_p1"
        exam["warnings"] = [str(exc)]
        return ok({"exam_id": exam_id, "status": "needs_p1", "jobs": jobs, "warnings": exam["warnings"]})

    exam["analysis"] = analysis
    exam["structure"] = _analysis_to_structure(exam_id, analysis)
    exam["status"] = "teacher_review"
    return ok({"exam_id": exam_id, "status": "teacher_review", "jobs": jobs})


@app.get("/exams/{exam_id}/structure")
def get_exam_structure(exam_id: str) -> dict:
    exam = _exam_or_404(exam_id)
    if exam.get("structure") is None:
        return ok(
            {
                "exam_id": exam_id,
                "status": exam["status"],
                "questions": [],
                "warnings": exam.get("warnings", []),
            }
        )
    return ok(exam["structure"])


@app.put("/exams/{exam_id}/questions/{exam_question_id}")
def update_question(exam_id: str, exam_question_id: str, payload: UpdateQuestionRequest) -> dict:
    exam = _exam_or_404(exam_id)
    structure = exam.get("structure")
    if not structure:
        raise HTTPException(status_code=404, detail={"message": "考试结构尚未生成"})

    for question in structure["questions"]:
        if question["exam_question_id"] == exam_question_id:
            update = payload.model_dump(exclude_none=True)
            question.update(update)
            return ok({"exam_question_id": exam_question_id, "updated": True})
    raise HTTPException(status_code=404, detail={"message": "题目不存在"})


@app.put("/exams/{exam_id}/questions/{exam_question_id}/knowledge-tags")
def confirm_knowledge_tags(exam_id: str, exam_question_id: str, payload: KnowledgeTagsRequest) -> dict:
    exam = _exam_or_404(exam_id)
    structure = exam.get("structure")
    if not structure:
        raise HTTPException(status_code=404, detail={"message": "考试结构尚未生成"})

    for question in structure["questions"]:
        if question["exam_question_id"] == exam_question_id:
            question["knowledge_point_ids"] = payload.knowledge_point_ids
            return ok(
                {
                    "exam_question_id": exam_question_id,
                    "knowledge_point_ids": payload.knowledge_point_ids,
                    "confirmed_by": "teacher_demo",
                    "confirmed_at": "",
                }
            )
    raise HTTPException(status_code=404, detail={"message": "题目不存在"})


@app.post("/exams/{exam_id}/diagnostics/run")
def run_exam_diagnostics(exam_id: str, payload: RunDiagnosticsRequest) -> dict:
    exam = _exam_or_404(exam_id)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=409, detail={"message": "请先完成考试解析"})
    diagnostic_id = f"diag_{uuid4().hex[:8]}"
    DIAGNOSTICS[diagnostic_id] = {
        "exam_id": exam_id,
        "request": payload.model_dump(),
    }
    return ok({"diagnostic_id": diagnostic_id, "status": "succeeded"})


@app.get("/exams/{exam_id}/diagnostics/{diagnostic_id}")
def get_exam_diagnostic(exam_id: str, diagnostic_id: str) -> dict:
    exam = _exam_or_404(exam_id)
    diagnostic = DIAGNOSTICS.get(diagnostic_id)
    if not diagnostic or diagnostic["exam_id"] != exam_id:
        raise HTTPException(status_code=404, detail={"message": "诊断报告不存在"})
    analysis: P2ExamAnalysis = exam["analysis"]
    return ok(_analysis_to_diagnostic(diagnostic_id, analysis))


@app.post("/exams/{exam_id}/lesson-plans")
def create_lesson_plan(exam_id: str, payload: LessonPlanRequest) -> dict:
    exam = _exam_or_404(exam_id)
    if exam.get("analysis") is None:
        raise HTTPException(status_code=409, detail={"message": "请先完成考试诊断"})
    filename = f"{exam_id}_lesson_plan.docx"
    return ok(
        {
            "lesson_plan_id": f"lesson_{uuid4().hex[:8]}",
            "file": {
                "file_id": f"file_lesson_{uuid4().hex[:8]}",
                "file_name": filename,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "storage_uri": f"local://exams/{exam_id}/{filename}",
            },
        }
    )


@app.get("/api/model/status")
def model_status() -> dict:
    return {
        "enabled": False,
        "base_url": "",
        "model": "rule-seed",
        "note": "第一阶段使用规则与P1知识点候选，不调用大模型。",
    }


@app.get("/api/p2/demo")
def p2_demo() -> dict:
    analysis = analyze_exam(
        paper_json_path=REPO_ROOT / "examples" / "normalized_paper_demo.json",
        score_file_path=REPO_ROOT / "examples" / "sample_exam_scores.xlsx",
        exam_id="exam_demo_001",
        class_name="示例班级",
    )
    return analysis.model_dump()


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
) -> dict:
    paper_content = await paper_file.read()
    score_content = await score_file.read()
    paper_suffix = _suffix_or_default(paper_file.filename, ".json")
    score_suffix = _suffix_or_default(score_file.filename, ".xlsx")

    try:
        with TemporaryDirectory(prefix="campus_p2_") as temp_dir:
            base = Path(temp_dir)
            paper_path = base / f"paper{paper_suffix}"
            score_path = base / f"scores{score_suffix}"
            paper_path.write_bytes(paper_content)
            score_path.write_bytes(score_content)
            analysis = analyze_exam(
                paper_json_path=paper_path,
                score_file_path=score_path,
                exam_id=exam_id,
                class_name=class_name,
            )
            return analysis.model_dump()
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


def _suffix_or_default(filename: str | None, default: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix or default


def _exam_or_404(exam_id: str) -> dict:
    exam = EXAMS.get(exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail={"message": "考试不存在"})
    return exam


def _file_or_404(file_id: str, exam_id: str) -> dict:
    file_record = FILES.get(file_id)
    if file_record is None or file_record["exam_id"] != exam_id:
        raise HTTPException(status_code=404, detail={"message": "文件不存在"})
    return file_record


def _analyze_uploaded_pair(paper: dict, score: dict, exam_id: str) -> P2ExamAnalysis:
    paper_suffix = Path(paper["metadata"]["file_name"]).suffix.lower()
    score_suffix = Path(score["metadata"]["file_name"]).suffix.lower() or ".xlsx"
    if paper_suffix != ".json":
        raise ValueError("当前独立 P2 包需要 P1 解析后的 paper.v0.1 JSON；Word/PDF/图片应先由 P1 /parse/paper 解析。")

    with TemporaryDirectory(prefix="campus_p2_standard_") as temp_dir:
        base = Path(temp_dir)
        paper_path = base / "paper.json"
        score_path = base / f"scores{score_suffix}"
        paper_path.write_bytes(paper["content"])
        score_path.write_bytes(score["content"])
        return analyze_exam(
            paper_json_path=paper_path,
            score_file_path=score_path,
            exam_id=exam_id,
            class_name="未命名班级",
        )


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
                "stem_html": f"<p>{item.stem_text}</p>" if item.stem_text else "",
                "knowledge_candidates": item.confirmed_knowledge_points,
                "knowledge_point_ids": [kp["code"] for kp in item.confirmed_knowledge_points],
                "needs_review": bool(item.warnings),
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
