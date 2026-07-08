from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient

from app.main import app
from campus_p2_core.p1_input.normalized_paper import validate_normalized_paper
from campus_p2_core.p2_teacher.service import P2TeacherService


def main() -> None:
    paper_path = ROOT / "examples" / "normalized_paper_demo.json"
    scores_path = ROOT / "examples" / "sample_exam_scores.xlsx"

    validation = validate_normalized_paper(paper_path)
    assert validation["ok"], validation
    assert validation["question_count"] == 18, validation

    result = P2TeacherService().run_analysis(
        paper_json_path=paper_path,
        score_file_path=scores_path,
        exam_id="p2_smoke_demo",
        class_name="高二3班",
        output_dir=ROOT / "data" / "exams",
    )
    analysis = result.analysis
    assert len(analysis.question_analysis) == 18
    assert len(analysis.p3_search_requests) == 8
    assert result.json_path.exists()
    assert result.markdown_path and result.markdown_path.exists()
    assert result.docx_path and result.docx_path.exists()

    client = TestClient(app)
    response = client.get("/api/p2/demo")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["question_analysis"]) == 18
    assert len(payload["p3_search_requests"]) == 8

    response = client.get("/api/p2/examples/paper")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert b"paper_demo_20260704_001" in response.content

    response = client.get("/api/p2/examples/scores")
    assert response.status_code == 200
    assert len(response.content) > 1_000

    with paper_path.open("rb") as paper_file, scores_path.open("rb") as score_file:
        response = client.post(
            "/api/p2/analyze",
            data={"exam_id": "api_smoke_demo", "class_name": "高二3班"},
            files={
                "paper_file": ("normalized_paper_demo.json", paper_file, "application/json"),
                "score_file": (
                    "sample_exam_scores.xlsx",
                    score_file,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["question_analysis"]) == 18
    assert len(payload["p3_search_requests"]) == 8

    response = client.post("/api/p2/reports/docx", json=payload)
    assert response.status_code == 200
    assert len(response.content) > 10_000

    response = client.post("/api/p2/reports/markdown", json=payload)
    assert response.status_code == 200
    assert "逐题分析" in response.text

    response = client.post(
        "/exams",
        json={
            "name": "Demo math exam",
            "subject": "math",
            "grade": "senior_high",
            "class_ids": ["class_demo"],
            "exam_date": "2026-07-08",
            "teacher_id": "teacher_demo",
        },
    )
    assert response.status_code == 200, response.text
    exam_id = response.json()["data"]["exam_id"]

    with scores_path.open("rb") as score_file:
        response = client.post(
            f"/exams/{exam_id}/files",
            data={"file_type": "score_excel"},
            files={
                "file": (
                    "sample_exam_scores.xlsx",
                    score_file,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert response.status_code == 200, response.text
    score_file_id = response.json()["data"]["file"]["file_id"]

    with paper_path.open("rb") as paper_file:
        response = client.post(
            f"/exams/{exam_id}/files",
            data={"file_type": "paper"},
            files={"file": ("normalized_paper_demo.json", paper_file, "application/json")},
        )
    assert response.status_code == 200, response.text
    paper_file_id = response.json()["data"]["file"]["file_id"]

    response = client.post(
        f"/exams/{exam_id}/parse",
        json={
            "score_file_id": score_file_id,
            "paper_file_id": paper_file_id,
            "auto_tag_knowledge": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "teacher_review"

    response = client.get(f"/exams/{exam_id}/structure")
    assert response.status_code == 200, response.text
    structure = response.json()["data"]
    assert len(structure["questions"]) == 18

    response = client.post(
        f"/exams/{exam_id}/diagnostics/run",
        json={
            "analysis_scope": "class",
            "class_id": "class_demo",
            "include_teaching_suggestions": True,
            "include_question_recommendations": True,
        },
    )
    assert response.status_code == 200, response.text
    diagnostic_id = response.json()["data"]["diagnostic_id"]

    response = client.get(f"/exams/{exam_id}/diagnostics/{diagnostic_id}")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"]["question_count"] == 18

    response = client.post(
        f"/exams/{exam_id}/lesson-plans",
        json={
            "diagnostic_id": diagnostic_id,
            "template_id": "tpl_school_math_review_v1",
            "sections": ["exam_summary", "high_loss_questions", "weakness_summary"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["file"]["file_name"].endswith(".docx")

    print("campus-system-p2 smoke test passed")
    print(f"questions={len(analysis.question_analysis)}")
    print(f"p3_requests={len(analysis.p3_search_requests)}")
    print(f"json={result.json_path}")
    print(f"markdown={result.markdown_path}")
    print(f"docx={result.docx_path}")


if __name__ == "__main__":
    main()
