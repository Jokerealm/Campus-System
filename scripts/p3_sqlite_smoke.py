from __future__ import annotations

import os
import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P3_BACKEND = ROOT / "campus_p3" / "backend"
sys.path.insert(0, str(P3_BACKEND))

os.environ.setdefault("P3_DATABASE_ENGINE", "sqlite")
os.environ.setdefault("P3_SQLITE_PATH", str(ROOT / "data" / "p3_demo.sqlite3"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
from django.core.management import call_command  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402


def main() -> None:
    django.setup()

    from resources.models import KnowledgePoint, QuestionBankItem  # noqa: WPS433

    call_command("migrate", "--noinput", verbosity=0)
    call_command("load_knowledge_points", verbosity=0)
    call_command("load_question_bank", verbosity=0)
    call_command("import_p1_papers_to_bank", verbosity=0)

    client = APIClient(HTTP_X_SERVICE_ID="p2-service")
    kp_response = client.get(
        "/api/resource/v1/knowledge-points?subject=math&stage=junior_middle_school&version=2026.1"
    )
    assert kp_response.status_code == 200, kp_response.content
    kp_items = kp_response.json()["data"]["items"]

    hs_kp_response = client.get(
        "/api/resource/v1/knowledge-points?subject=math&stage=senior_high&version=2026.1"
    )
    assert hs_kp_response.status_code == 200, hs_kp_response.content
    hs_kp_items = hs_kp_response.json()["data"]["items"]
    assert "???" not in json.dumps(hs_kp_items, ensure_ascii=False), hs_kp_items[:5]

    search_response = client.post(
        "/api/resource/v1/questions/search",
        {
            "knowledge_point_ids": ["kp_math_8_function_linear"],
            "difficulty_range": [0.35, 0.75],
            "source_priority": ["school_bank", "exam_history", "middle_exam_real"],
            "limit": 3,
        },
        format="json",
    )
    assert search_response.status_code == 200, search_response.content
    search_data = search_response.json()["data"]

    hs_search_response = client.post(
        "/api/resource/v1/questions/search",
        {
            "knowledge_point_ids": ["kp_hs_kp_func_deriv_002"],
            "difficulty_range": [0.35, 0.75],
            "limit": 3,
        },
        format="json",
    )
    assert hs_search_response.status_code == 200, hs_search_response.content
    hs_search_data = hs_search_response.json()["data"]
    assert len(hs_search_data["items"]) >= 1, hs_search_data
    assert "???" not in json.dumps(hs_search_data["items"], ensure_ascii=False), hs_search_data

    p1_search_response = client.post(
        "/api/resource/v1/questions/search",
        {
            "knowledge_point_ids": ["kp_math_junior_statistics"],
            "difficulty_range": [0.35, 0.75],
            "source_priority": ["middle_exam_real", "school_bank", "exam_history"],
            "limit": 5,
        },
        format="json",
    )
    assert p1_search_response.status_code == 200, p1_search_response.content
    p1_search_data = p1_search_response.json()["data"]
    assert len(p1_search_data["items"]) >= 3, p1_search_data
    assert QuestionBankItem.objects.count() >= 1_200
    assert KnowledgePoint.objects.count() >= 300

    stats_response = client.get("/api/resource/v1/stats?version=2026.1")
    assert stats_response.status_code == 200, stats_response.content
    stats_data = stats_response.json()["data"]
    assert stats_data["knowledge_point_count"] == KnowledgePoint.objects.count()
    assert stats_data["question_count"] == QuestionBankItem.objects.count()
    assert stats_data["approved_question_count"] >= 1_200
    assert stats_data["question_source_counts"]["middle_exam_real"] >= 1_200

    print("p3 sqlite smoke passed")
    print(f"db_knowledge_points={KnowledgePoint.objects.count()}")
    print(f"db_questions={QuestionBankItem.objects.count()}")
    print(f"api_approved_questions={stats_data['approved_question_count']}")
    print(f"api_junior_knowledge_points={len(kp_items)}")
    print(f"api_senior_knowledge_points={len(hs_kp_items)}")
    print(f"junior_search_items={len(search_data['items'])}")
    print(f"junior_need_ai_generation={search_data['need_ai_generation']}")
    print(f"senior_search_items={len(hs_search_data['items'])}")
    print(f"senior_need_ai_generation={hs_search_data['need_ai_generation']}")
    print(f"p1_imported_search_items={len(p1_search_data['items'])}")
    print(f"p1_imported_need_ai_generation={p1_search_data['need_ai_generation']}")


if __name__ == "__main__":
    main()
