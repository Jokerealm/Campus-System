from __future__ import annotations

import json
from pathlib import Path

from campus_p2_core.contracts.paper import NormalizedPaper


def load_normalized_paper(path: str | Path) -> NormalizedPaper:
    paper_path = Path(path)
    with paper_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return NormalizedPaper.model_validate(payload)


def validate_normalized_paper(path: str | Path) -> dict:
    paper = load_normalized_paper(path)
    question_nos = [q.question_no for q in paper.questions]
    duplicated = sorted({no for no in question_nos if question_nos.count(no) > 1})
    review_count = len([q for q in paper.questions if q.needs_review or q.parse_confidence < 0.75])
    no_knowledge = [q.question_no for q in paper.questions if not q.knowledge_candidates]
    return {
        "paper_id": paper.paper_id,
        "schema_version": paper.schema_version,
        "question_count": len(paper.questions),
        "duplicated_question_nos": duplicated,
        "needs_review_count": review_count,
        "questions_without_knowledge": no_knowledge,
        "ok": not duplicated,
    }

