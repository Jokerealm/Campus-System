from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


QuestionType = Literal["single_choice", "multiple_choice", "blank", "solution"]
Stage = Literal["junior_high", "senior_high"]


class PaperSource(BaseModel):
    name: str
    provider: str = "manual_import"
    original_file: str = ""


class OptionItem(BaseModel):
    label: str
    text: str


class ImageRef(BaseModel):
    image_id: str
    path: str
    role: str = "stem"


class KnowledgeCandidate(BaseModel):
    code: str
    name: str
    confidence: float = Field(ge=0, le=1)
    source: str = "manual"


class NormalizedQuestion(BaseModel):
    question_id: str
    question_no: str
    question_type: QuestionType
    stem_text: str
    stem_markdown: str = ""
    options: list[OptionItem] = Field(default_factory=list)
    answer: str = ""
    solution: str = ""
    full_score: float | None = None
    images: list[ImageRef] = Field(default_factory=list)
    knowledge_candidates: list[KnowledgeCandidate] = Field(default_factory=list)
    difficulty: int = Field(default=3, ge=1, le=5)
    parse_confidence: float = Field(default=1.0, ge=0, le=1)
    needs_review: bool = False

    def display_stem(self) -> str:
        return self.stem_markdown or self.stem_text


class NormalizedPaper(BaseModel):
    schema_version: Literal["paper.v0.1"]
    paper_id: str
    source: PaperSource
    subject: Literal["math"] = "math"
    stage: Stage = "senior_high"
    grade: str
    questions: list[NormalizedQuestion]
