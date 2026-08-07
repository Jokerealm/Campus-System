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
    stem_markdown: str = ""
    options: list[dict] = Field(default_factory=list)
    question_type: str | None = None
    images: list[dict] = Field(default_factory=list)
    parse_confidence: float = Field(default=1.0, ge=0, le=1)
    needs_review: bool = False
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
    knowledge_point_ids: list[str] = Field(default_factory=list)
    question_type: str | None = None
    difficulty_range: tuple[float, float] = (0.35, 0.75)
    limit: int = 5
    exclude_question_ids: list[str] = Field(default_factory=list)


class QuestionRecommendation(BaseModel):
    bank_question_id: str
    source: str
    content_html: str
    answer_html: str = ""
    analysis_html: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    question_type: str = ""
    difficulty: float = 0.5
    match_score: float = 0.0
    recommend_reason: str = ""


class PracticeRecommendationGroup(BaseModel):
    knowledge_point_code: str
    knowledge_point_id: str = ""
    knowledge_point_name: str
    score_rate: float = 0
    loss_rate: float = 0
    severity: Severity
    related_question_nos: list[str] = Field(default_factory=list)
    items: list[QuestionRecommendation] = Field(default_factory=list)
    need_ai_generation: bool = False
    source: str = "fixture"


class PracticePackResult(BaseModel):
    practice_pack_id: str
    status: str
    title: str
    target: str = "class"
    target_ref_id: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    source: str = "p3-http"
    needs_p3_sync: bool = False
    message: str = ""


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
    knowledge_tag_coverage: float = 0
    question_analysis: list[QuestionAnalysis]
    knowledge_diagnostics: list[KnowledgeDiagnostic]
    p3_search_requests: list[P3SearchRequest]
    practice_recommendations: list[PracticeRecommendationGroup] = Field(default_factory=list)
    practice_packs: list[PracticePackResult] = Field(default_factory=list)
    teaching_report: TeachingReport
    warnings: list[str] = Field(default_factory=list)

