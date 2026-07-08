from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["stable", "watch", "weak", "critical"]


class ScoreRecord(BaseModel):
    question_no: str
    full_score: float = Field(gt=0)
    avg_score: float = Field(ge=0)
    sample_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class QuestionAnalysis(BaseModel):
    question_id: str | None = None
    question_no: str
    full_score: float
    avg_score: float
    score_rate: float
    loss_rate: float
    confirmed_knowledge_points: list[dict]
    severity: Severity
    teacher_review_status: Literal["pending", "confirmed"] = "pending"
    stem_text: str = ""
    question_type: str | None = None
    warnings: list[str] = Field(default_factory=list)


class KnowledgeDiagnostic(BaseModel):
    code: str
    name: str
    score_rate: float
    loss_rate: float
    severity: Severity
    related_question_nos: list[str]
    suggestion: str


class P3SearchRequest(BaseModel):
    knowledge_point_codes: list[str]
    question_type: str | None = None
    difficulty_range: tuple[int, int] = (1, 4)
    limit: int = 5
    exclude_question_ids: list[str] = Field(default_factory=list)


class TeachingReport(BaseModel):
    title: str
    summary: str
    priority_question_nos: list[str]
    weak_knowledge_points: list[str]
    markdown: str


class P2ExamAnalysis(BaseModel):
    exam_id: str
    paper_id: str
    class_name: str
    question_analysis: list[QuestionAnalysis]
    knowledge_diagnostics: list[KnowledgeDiagnostic]
    p3_search_requests: list[P3SearchRequest]
    teaching_report: TeachingReport
    warnings: list[str] = Field(default_factory=list)

