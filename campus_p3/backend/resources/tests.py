import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient

from .models import GeneratedQuestion, KnowledgePoint, PracticePack, QuestionBankItem


class ResourceIdentityApiTests(TestCase):
    def test_resource_api_rejects_missing_identity(self):
        response = APIClient().get("/api/resource/v1/knowledge-points")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "UNAUTHORIZED")

    def test_resource_api_accepts_service_identity(self):
        response = APIClient(HTTP_X_SERVICE_ID="p2-service").get(
            "/api/resource/v1/knowledge-points"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "OK")

    def test_resource_api_forbids_student_identity(self):
        response = APIClient(HTTP_X_STUDENT_ID="student_001").get(
            "/api/resource/v1/knowledge-points"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "FORBIDDEN")


class KnowledgePointApiTests(TestCase):
    def setUp(self):
        self.client = APIClient(HTTP_X_TEACHER_ID="teacher_001")
        KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function",
            code="MATH.8.FUNC",
            name="函数",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数"],
            sort_order=10,
        )
        KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质",
            parent_id="kp_math_8_function",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
            sort_order=20,
        )
        KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_disabled",
            code="MATH.DISABLED.001",
            name="停用知识点",
            subject="math",
            stage="junior_middle_school",
            grade_range=["9"],
            path=["停用知识点"],
            enabled=False,
            sort_order=30,
        )
        KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质旧版",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
            version="2025.1",
            sort_order=40,
        )

    def test_list_uses_default_version_and_standard_response_shape(self):
        response = self.client.get("/api/resource/v1/knowledge-points", HTTP_X_REQUEST_ID="req_kp_001")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req_kp_001")
        self.assertEqual(payload["code"], "OK")
        self.assertEqual(payload["message"], "success")
        self.assertEqual(payload["data"]["version"], KnowledgePoint.DEFAULT_VERSION)
        self.assertEqual(
            [item["knowledge_point_id"] for item in payload["data"]["items"]],
            ["kp_math_8_function", "kp_math_8_function_linear", "kp_math_disabled"],
        )

    def test_list_filters_by_subject_stage_and_enabled(self):
        response = self.client.get(
            "/api/resource/v1/knowledge-points",
            {
                "subject": "math",
                "stage": "junior_middle_school",
                "enabled": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        item_ids = [item["knowledge_point_id"] for item in response.json()["data"]["items"]]
        self.assertEqual(item_ids, ["kp_math_8_function", "kp_math_8_function_linear"])

    def test_list_filters_by_requested_version(self):
        response = self.client.get("/api/resource/v1/knowledge-points", {"version": "2025.1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["version"], "2025.1")
        self.assertEqual(len(payload["data"]["items"]), 1)
        self.assertEqual(payload["data"]["items"][0]["knowledge_point_id"], "kp_math_8_function_linear")
        self.assertEqual(payload["data"]["items"][0]["name"], "一次函数图像与性质旧版")

    def test_same_knowledge_point_id_can_exist_in_multiple_versions(self):
        self.assertEqual(
            KnowledgePoint.objects.filter(knowledge_point_id="kp_math_8_function_linear").count(),
            2,
        )

    def test_invalid_filter_returns_validation_error(self):
        response = self.client.get("/api/resource/v1/knowledge-points", {"enabled": "unknown"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("enabled", response.json()["data"])


class LoadKnowledgePointsCommandTests(TestCase):
    def test_load_knowledge_points_is_idempotent(self):
        first_stdout = StringIO()
        call_command("load_knowledge_points", stdout=first_stdout)

        self.assertEqual(KnowledgePoint.objects.count(), 10)
        self.assertIn("10 created", first_stdout.getvalue())

        second_stdout = StringIO()
        call_command("load_knowledge_points", stdout=second_stdout)

        self.assertEqual(KnowledgePoint.objects.count(), 10)
        self.assertIn("10 updated", second_stdout.getvalue())

    def test_load_knowledge_points_keeps_versions_separate(self):
        call_command("load_knowledge_points", stdout=StringIO())

        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "knowledge_points_2027_1.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "knowledge_point_id": "kp_math_8_function_linear",
                            "code": "MATH.8.FUNC.001",
                            "name": "一次函数图像与性质新版",
                            "subject": "math",
                            "stage": "junior_middle_school",
                            "grade_range": ["8"],
                            "path": ["数与代数", "函数", "一次函数图像与性质"],
                            "version": "2027.1",
                            "enabled": True,
                            "sort_order": 50,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            call_command("load_knowledge_points", source=str(source), stdout=StringIO())

        self.assertEqual(KnowledgePoint.objects.count(), 11)
        old_point = KnowledgePoint.objects.get(
            knowledge_point_id="kp_math_8_function_linear",
            version="2026.1",
        )
        new_point = KnowledgePoint.objects.get(
            knowledge_point_id="kp_math_8_function_linear",
            version="2027.1",
        )
        self.assertEqual(old_point.name, "一次函数图像与性质")
        self.assertEqual(new_point.name, "一次函数图像与性质新版")

    def test_load_knowledge_points_rejects_missing_required_fields(self):
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "invalid_knowledge_points.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "knowledge_point_id": "kp_invalid",
                            "name": "缺少编码的知识点",
                            "subject": "math",
                            "stage": "junior_middle_school",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "Item at index 0 is missing code."):
                call_command("load_knowledge_points", source=str(source), stdout=StringIO())


class QuestionBankApiTests(TestCase):
    def setUp(self):
        self.client = APIClient(HTTP_X_TEACHER_ID="teacher_001")
        self.linear_function = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
        )
        self.function_application = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_application",
            code="MATH.8.FUNC.002",
            name="一次函数实际应用",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数实际应用"],
        )
        self.triangle = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_triangle",
            code="MATH.8.GEO.001",
            name="三角形全等",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["图形与几何", "三角形", "三角形全等"],
        )

    def test_import_questions_creates_items_and_links_knowledge_points(self):
        response = self.client.post(
            "/api/resource/v1/questions/import",
            {
                "source": "school_bank",
                "items": [
                    {
                        "content_html": "<p>已知一次函数 y=2x+1。</p>",
                        "answer_html": "<p>略。</p>",
                        "analysis_html": "<p>代入计算。</p>",
                        "knowledge_point_ids": ["kp_math_8_function_linear"],
                        "question_type": "填空题",
                        "difficulty": 0.35,
                    }
                ],
            },
            format="json",
            HTTP_X_REQUEST_ID="req_question_import_001",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req_question_import_001")
        self.assertEqual(payload["code"], "OK")
        self.assertEqual(payload["data"]["created_count"], 1)
        self.assertEqual(payload["data"]["updated_count"], 0)
        bank_question_id = payload["data"]["items"][0]["bank_question_id"]
        question = QuestionBankItem.objects.get(bank_question_id=bank_question_id)
        self.assertEqual(question.source, "school_bank")
        self.assertEqual(
            list(question.knowledge_points.values_list("knowledge_point_id", flat=True)),
            ["kp_math_8_function_linear"],
        )

    def test_import_questions_rejects_unknown_knowledge_point(self):
        response = self.client.post(
            "/api/resource/v1/questions/import",
            {
                "source": "school_bank",
                "items": [
                    {
                        "content_html": "<p>题干。</p>",
                        "answer_html": "<p>答案。</p>",
                        "analysis_html": "<p>解析。</p>",
                        "knowledge_point_ids": ["kp_missing"],
                        "question_type": "填空题",
                        "difficulty": 0.35,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("knowledge_point_ids", response.json()["data"])

    def test_import_questions_rejects_ai_generated_source(self):
        response = self.client.post(
            "/api/resource/v1/questions/import",
            {
                "source": "ai_generated",
                "items": [
                    {
                        "content_html": "<p>AI 题干。</p>",
                        "answer_html": "<p>答案。</p>",
                        "analysis_html": "<p>解析。</p>",
                        "knowledge_point_ids": ["kp_math_8_function_linear"],
                        "question_type": "填空题",
                        "difficulty": 0.35,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("source", response.json()["data"])
        self.assertEqual(QuestionBankItem.objects.count(), 0)

    def test_import_cannot_overwrite_an_approved_ai_question(self):
        question = QuestionBankItem.objects.create(
            bank_question_id="bq_ai_published",
            source=QuestionBankItem.Source.AI_GENERATED,
            content_html="<p>已审核 AI 题干。</p>",
            answer_html="<p>A</p>",
            analysis_html="<p>已审核解析。</p>",
            question_type="选择题",
            difficulty=0.5,
            audit_status=QuestionBankItem.AuditStatus.APPROVED,
        )
        question.knowledge_points.add(self.linear_function)

        response = self.client.post(
            "/api/resource/v1/questions/import",
            {
                "source": "school_bank",
                "items": [
                    {
                        "bank_question_id": question.bank_question_id,
                        "content_html": "<p>试图绕过审核的题干。</p>",
                        "answer_html": "<p>B</p>",
                        "analysis_html": "<p>未审核解析。</p>",
                        "knowledge_point_ids": [
                            self.linear_function.knowledge_point_id
                        ],
                        "question_type": "选择题",
                        "difficulty": 0.2,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "CONFLICT")
        question.refresh_from_db()
        self.assertEqual(question.source, QuestionBankItem.Source.AI_GENERATED)
        self.assertEqual(question.content_html, "<p>已审核 AI 题干。</p>")

    def test_import_cannot_change_an_existing_question_source(self):
        question = self._create_question(
            bank_question_id="bq_fixed_source",
            source=QuestionBankItem.Source.SCHOOL_BANK,
            difficulty=0.5,
            question_type="选择题",
            knowledge_points=[self.linear_function],
        )

        response = self.client.post(
            "/api/resource/v1/questions/import",
            {
                "source": "exam_history",
                "items": [
                    {
                        "bank_question_id": question.bank_question_id,
                        "content_html": "<p>更新题干。</p>",
                        "answer_html": "<p>A</p>",
                        "analysis_html": "<p>更新解析。</p>",
                        "knowledge_point_ids": [
                            self.linear_function.knowledge_point_id
                        ],
                        "question_type": "选择题",
                        "difficulty": 0.5,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        question.refresh_from_db()
        self.assertEqual(question.source, QuestionBankItem.Source.SCHOOL_BANK)

    def test_search_questions_filters_and_orders_by_source_priority(self):
        self._create_question(
            bank_question_id="bq_school",
            source="school_bank",
            difficulty=0.45,
            question_type="解答题",
            knowledge_points=[self.linear_function],
        )
        self._create_question(
            bank_question_id="bq_exam",
            source="exam_history",
            difficulty=0.55,
            question_type="解答题",
            knowledge_points=[self.linear_function, self.function_application],
        )
        self._create_question(
            bank_question_id="bq_draft",
            source="exam_history",
            difficulty=0.5,
            question_type="解答题",
            knowledge_points=[self.linear_function],
            audit_status=QuestionBankItem.AuditStatus.DRAFT,
        )

        response = self.client.post(
            "/api/resource/v1/questions/search",
            {
                "knowledge_point_ids": ["kp_math_8_function_linear"],
                "question_type": "解答题",
                "difficulty_range": [0.4, 0.7],
                "source_priority": ["exam_history", "school_bank"],
                "limit": 2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertFalse(payload["need_ai_generation"])
        self.assertEqual(
            [item["bank_question_id"] for item in payload["items"]],
            ["bq_exam", "bq_school"],
        )
        self.assertEqual(payload["items"][0]["match_score"], 1.0)
        self.assertEqual(
            payload["items"][0]["knowledge_point_ids"],
            ["kp_math_8_function_linear", "kp_math_8_function_application"],
        )

    def test_source_priority_orders_without_excluding_unlisted_sources(self):
        self._create_question(
            bank_question_id="bq_external",
            source="external_import",
            difficulty=0.3,
            question_type="解答题",
            knowledge_points=[self.linear_function],
        )
        self._create_question(
            bank_question_id="bq_school",
            source="school_bank",
            difficulty=0.6,
            question_type="解答题",
            knowledge_points=[self.linear_function],
        )

        response = self.client.post(
            "/api/resource/v1/questions/search",
            {
                "knowledge_point_ids": ["kp_math_8_function_linear"],
                "source_priority": ["school_bank"],
                "limit": 2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertFalse(payload["need_ai_generation"])
        self.assertEqual(
            [item["bank_question_id"] for item in payload["items"]],
            ["bq_school", "bq_external"],
        )

    def test_search_questions_marks_need_ai_generation_when_results_are_insufficient(self):
        self._create_question(
            bank_question_id="bq_triangle",
            source="middle_exam_real",
            difficulty=0.58,
            question_type="解答题",
            knowledge_points=[self.triangle],
        )

        response = self.client.post(
            "/api/resource/v1/questions/search",
            {
                "knowledge_point_ids": ["kp_math_8_triangle"],
                "limit": 3,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(len(payload["items"]), 1)
        self.assertTrue(payload["need_ai_generation"])

    def _create_question(
        self,
        bank_question_id,
        source,
        difficulty,
        question_type,
        knowledge_points,
        audit_status=QuestionBankItem.AuditStatus.APPROVED,
    ):
        question = QuestionBankItem.objects.create(
            bank_question_id=bank_question_id,
            source=source,
            content_html=f"<p>{bank_question_id} 题干。</p>",
            answer_html="<p>答案。</p>",
            analysis_html="<p>解析。</p>",
            question_type=question_type,
            difficulty=difficulty,
            audit_status=audit_status,
            knowledge_point_version=KnowledgePoint.DEFAULT_VERSION,
        )
        question.knowledge_points.set(knowledge_points)
        return question


class GeneratedQuestionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient(HTTP_X_TEACHER_ID="teacher_001")
        self.linear_function = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
        )
        self.function_application = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_application",
            code="MATH.8.FUNC.002",
            name="一次函数实际应用",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数实际应用"],
        )

    def test_import_generated_questions_creates_pending_candidates(self):
        response = self.client.post(
            "/api/resource/v1/generated-questions",
            {
                "source_question_id": "bq_source_001",
                "model_name": "mock-generator",
                "prompt_version": "p1.0",
                "raw_request": {"limit": 1},
                "items": [
                    {
                        "generated_question_id": "genq_linear_001",
                        "content_html": "<p>已知一次函数 y=2x+1。</p>",
                        "answer_html": "<p>略。</p>",
                        "analysis_html": "<p>代入计算。</p>",
                        "knowledge_point_ids": ["kp_math_8_function_linear"],
                        "question_type": "填空题",
                        "difficulty": 0.42,
                        "validation": {"logic_checked": True},
                        "raw_response": {"candidate_index": 0},
                    }
                ],
            },
            format="json",
            HTTP_X_REQUEST_ID="req_genq_import_001",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req_genq_import_001")
        self.assertEqual(payload["code"], "OK")
        self.assertEqual(payload["data"]["saved_count"], 1)
        self.assertEqual(payload["data"]["created_count"], 1)
        self.assertEqual(payload["data"]["audit_status"], GeneratedQuestion.AuditStatus.PENDING_REVIEW)

        generated_question = GeneratedQuestion.objects.get(generated_question_id="genq_linear_001")
        self.assertEqual(generated_question.source_question_id, "bq_source_001")
        self.assertEqual(generated_question.audit_status, GeneratedQuestion.AuditStatus.PENDING_REVIEW)
        self.assertEqual(generated_question.model_name, "mock-generator")
        self.assertEqual(generated_question.prompt_version, "p1.0")
        self.assertEqual(generated_question.validation, {"logic_checked": True})
        self.assertEqual(
            list(generated_question.knowledge_points.values_list("knowledge_point_id", flat=True)),
            ["kp_math_8_function_linear"],
        )

    def test_import_generated_questions_rejects_unknown_knowledge_point(self):
        response = self.client.post(
            "/api/resource/v1/generated-questions",
            {
                "items": [
                    {
                        "content_html": "<p>题干。</p>",
                        "answer_html": "<p>答案。</p>",
                        "analysis_html": "<p>解析。</p>",
                        "knowledge_point_ids": ["kp_missing"],
                        "question_type": "填空题",
                        "difficulty": 0.4,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("knowledge_point_ids", response.json()["data"])
        self.assertEqual(GeneratedQuestion.objects.count(), 0)

    def test_import_generated_questions_updates_pending_candidate(self):
        self._create_generated_question(
            generated_question_id="genq_pending_update",
            knowledge_points=[self.linear_function],
        )

        response = self.client.post(
            "/api/resource/v1/generated-questions",
            {
                "source_question_id": "bq_source_002",
                "items": [
                    {
                        "generated_question_id": "genq_pending_update",
                        "content_html": "<p>更新后的题干。</p>",
                        "answer_html": "<p>更新后的答案。</p>",
                        "analysis_html": "<p>更新后的解析。</p>",
                        "knowledge_point_ids": [
                            "kp_math_8_function_linear",
                            "kp_math_8_function_application",
                        ],
                        "question_type": "填空题",
                        "difficulty": 0.5,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["created_count"], 0)
        self.assertEqual(payload["updated_count"], 1)

        generated_question = GeneratedQuestion.objects.get(
            generated_question_id="genq_pending_update"
        )
        self.assertEqual(generated_question.source_question_id, "bq_source_002")
        self.assertEqual(generated_question.content_html, "<p>更新后的题干。</p>")
        self.assertEqual(generated_question.question_type, "填空题")
        self.assertEqual(generated_question.difficulty, 0.5)
        self.assertEqual(generated_question.audit_status, GeneratedQuestion.AuditStatus.PENDING_REVIEW)
        self.assertEqual(
            sorted(generated_question.knowledge_points.values_list("knowledge_point_id", flat=True)),
            ["kp_math_8_function_application", "kp_math_8_function_linear"],
        )

    def test_list_and_detail_generated_questions(self):
        self._create_generated_question(
            generated_question_id="genq_pending",
            knowledge_points=[self.linear_function],
        )
        self._create_generated_question(
            generated_question_id="genq_rejected",
            knowledge_points=[self.function_application],
            audit_status=GeneratedQuestion.AuditStatus.REJECTED,
        )

        list_response = self.client.get(
            "/api/resource/v1/generated-questions",
            {
                "audit_status": "pending_review",
                "knowledge_point_id": "kp_math_8_function_linear",
            },
        )

        self.assertEqual(list_response.status_code, 200)
        items = list_response.json()["data"]["items"]
        self.assertEqual([item["generated_question_id"] for item in items], ["genq_pending"])
        self.assertIsNone(items[0]["bank_question_id"])

        detail_response = self.client.get("/api/resource/v1/generated-questions/genq_pending")

        self.assertEqual(detail_response.status_code, 200)
        payload = detail_response.json()["data"]
        self.assertEqual(payload["generated_question_id"], "genq_pending")
        self.assertEqual(payload["knowledge_point_ids"], ["kp_math_8_function_linear"])

    def test_review_approve_publishes_generated_question_to_bank(self):
        self._create_generated_question(
            generated_question_id="genq_to_approve",
            knowledge_points=[self.linear_function, self.function_application],
        )

        response = self.client.put(
            "/api/resource/v1/generated-questions/genq_to_approve/review",
            {
                "decision": "approved",
                "reviewer_id": "teacher_001",
                "review_comment": "通过，可加入校本题库。",
                "publish_to_bank": True,
            },
            format="json",
            HTTP_X_REQUEST_ID="req_genq_review_001",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req_genq_review_001")
        self.assertEqual(payload["code"], "OK")
        self.assertEqual(payload["data"]["audit_status"], GeneratedQuestion.AuditStatus.APPROVED)
        self.assertTrue(payload["data"]["bank_question_id"].startswith("bq_"))

        generated_question = GeneratedQuestion.objects.get(generated_question_id="genq_to_approve")
        self.assertEqual(generated_question.audit_status, GeneratedQuestion.AuditStatus.APPROVED)
        self.assertEqual(generated_question.reviewer_id, "teacher_001")
        self.assertEqual(generated_question.review_comment, "通过，可加入校本题库。")
        self.assertIsNotNone(generated_question.reviewed_at)
        self.assertEqual(
            generated_question.bank_question.bank_question_id,
            payload["data"]["bank_question_id"],
        )

        bank_question = generated_question.bank_question
        self.assertEqual(bank_question.source, QuestionBankItem.Source.AI_GENERATED)
        self.assertEqual(bank_question.audit_status, QuestionBankItem.AuditStatus.APPROVED)
        self.assertEqual(bank_question.content_html, generated_question.content_html)
        self.assertEqual(bank_question.question_type, generated_question.question_type)
        self.assertEqual(
            sorted(bank_question.knowledge_points.values_list("knowledge_point_id", flat=True)),
            ["kp_math_8_function_application", "kp_math_8_function_linear"],
        )

    def test_review_reject_does_not_publish_to_bank(self):
        self._create_generated_question(
            generated_question_id="genq_to_reject",
            knowledge_points=[self.linear_function],
        )

        response = self.client.put(
            "/api/resource/v1/generated-questions/genq_to_reject/review",
            {
                "decision": "rejected",
                "reviewer_id": "teacher_001",
                "review_comment": "解析不够严谨。",
                "publish_to_bank": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["audit_status"], GeneratedQuestion.AuditStatus.REJECTED)
        self.assertIsNone(payload["bank_question_id"])
        self.assertEqual(QuestionBankItem.objects.count(), 0)

        generated_question = GeneratedQuestion.objects.get(generated_question_id="genq_to_reject")
        self.assertEqual(generated_question.audit_status, GeneratedQuestion.AuditStatus.REJECTED)
        self.assertIsNone(generated_question.bank_question)

    def test_teacher_review_rejects_mismatched_reviewer_id(self):
        self._create_generated_question(
            generated_question_id="genq_reviewer_mismatch",
            knowledge_points=[self.linear_function],
        )

        response = self.client.put(
            "/api/resource/v1/generated-questions/genq_reviewer_mismatch/review",
            {
                "decision": "approved",
                "reviewer_id": "teacher_other",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("reviewer_id", response.json()["data"])
        generated_question = GeneratedQuestion.objects.get(
            generated_question_id="genq_reviewer_mismatch"
        )
        self.assertEqual(
            generated_question.audit_status,
            GeneratedQuestion.AuditStatus.PENDING_REVIEW,
        )
        self.assertEqual(QuestionBankItem.objects.count(), 0)

    def test_review_rejects_already_reviewed_generated_question(self):
        self._create_generated_question(
            generated_question_id="genq_reviewed",
            knowledge_points=[self.linear_function],
            audit_status=GeneratedQuestion.AuditStatus.APPROVED,
        )

        response = self.client.put(
            "/api/resource/v1/generated-questions/genq_reviewed/review",
            {
                "decision": "rejected",
                "reviewer_id": "teacher_001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "CONFLICT")
        self.assertEqual(QuestionBankItem.objects.count(), 0)

    def test_import_rejects_overwriting_reviewed_generated_question(self):
        self._create_generated_question(
            generated_question_id="genq_reviewed",
            knowledge_points=[self.linear_function],
            audit_status=GeneratedQuestion.AuditStatus.REJECTED,
        )

        response = self.client.post(
            "/api/resource/v1/generated-questions",
            {
                "items": [
                    {
                        "generated_question_id": "genq_reviewed",
                        "content_html": "<p>新的题干。</p>",
                        "answer_html": "<p>答案。</p>",
                        "analysis_html": "<p>解析。</p>",
                        "knowledge_point_ids": ["kp_math_8_function_linear"],
                        "question_type": "填空题",
                        "difficulty": 0.4,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "CONFLICT")

    def _create_generated_question(
        self,
        generated_question_id,
        knowledge_points,
        audit_status=GeneratedQuestion.AuditStatus.PENDING_REVIEW,
    ):
        generated_question = GeneratedQuestion.objects.create(
            generated_question_id=generated_question_id,
            source_question_id="bq_source_001",
            content_html=f"<p>{generated_question_id} 题干。</p>",
            answer_html="<p>答案。</p>",
            analysis_html="<p>解析。</p>",
            question_type="解答题",
            difficulty=0.45,
            validation={"logic_checked": True},
            audit_status=audit_status,
            knowledge_point_version=KnowledgePoint.DEFAULT_VERSION,
            model_name="mock-generator",
            prompt_version="p1.0",
            raw_request={"limit": 1},
            raw_response={"candidate_index": 0},
        )
        generated_question.knowledge_points.set(knowledge_points)
        return generated_question


class PracticePackApiTests(TestCase):
    def setUp(self):
        self.client = APIClient(HTTP_X_TEACHER_ID="teacher_001")
        self.linear_function = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
        )
        self.function_application = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_application",
            code="MATH.8.FUNC.002",
            name="一次函数实际应用",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数实际应用"],
        )
        self.approved_question = self._create_question(
            bank_question_id="bq_pack_approved",
            knowledge_points=[self.linear_function],
        )
        self.draft_question = self._create_question(
            bank_question_id="bq_pack_draft",
            knowledge_points=[self.linear_function],
            audit_status=QuestionBankItem.AuditStatus.DRAFT,
        )

    def test_create_practice_pack_creates_links(self):
        response = self.client.post(
            "/api/resource/v1/practice-packs",
            {
                "title": "一次函数薄弱点强化训练",
                "target": "class",
                "target_ref_id": "class_8_3",
                "knowledge_point_ids": [
                    "kp_math_8_function_linear",
                    "kp_math_8_function_application",
                ],
                "question_ids": ["bq_pack_approved"],
                "created_by": "teacher_001",
            },
            format="json",
            HTTP_X_REQUEST_ID="req_pack_001",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["request_id"], "req_pack_001")
        self.assertEqual(payload["code"], "OK")
        self.assertEqual(payload["data"]["status"], PracticePack.Status.DRAFT)
        self.assertTrue(payload["data"]["practice_pack_id"].startswith("pack_"))

        practice_pack = PracticePack.objects.get(
            practice_pack_id=payload["data"]["practice_pack_id"]
        )
        self.assertEqual(practice_pack.title, "一次函数薄弱点强化训练")
        self.assertEqual(practice_pack.target, PracticePack.Target.CLASS)
        self.assertEqual(practice_pack.target_ref_id, "class_8_3")
        self.assertEqual(practice_pack.created_by, "teacher_001")
        self.assertEqual(practice_pack.knowledge_point_version, KnowledgePoint.DEFAULT_VERSION)
        self.assertEqual(
            sorted(practice_pack.knowledge_points.values_list("knowledge_point_id", flat=True)),
            ["kp_math_8_function_application", "kp_math_8_function_linear"],
        )
        self.assertEqual(
            list(practice_pack.questions.values_list("bank_question_id", flat=True)),
            ["bq_pack_approved"],
        )

    def test_create_practice_pack_rejects_unknown_knowledge_point(self):
        response = self.client.post(
            "/api/resource/v1/practice-packs",
            {
                "title": "一次函数薄弱点强化训练",
                "target": "class",
                "target_ref_id": "class_8_3",
                "knowledge_point_ids": ["kp_missing"],
                "question_ids": ["bq_pack_approved"],
                "created_by": "teacher_001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("knowledge_point_ids", response.json()["data"])
        self.assertEqual(PracticePack.objects.count(), 0)

    def test_teacher_create_pack_rejects_mismatched_created_by(self):
        response = self.client.post(
            "/api/resource/v1/practice-packs",
            {
                "title": "一次函数强化训练",
                "target": "class",
                "target_ref_id": "class_8_3",
                "knowledge_point_ids": ["kp_math_8_function_linear"],
                "question_ids": ["bq_pack_approved"],
                "created_by": "teacher_other",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("created_by", response.json()["data"])
        self.assertEqual(PracticePack.objects.count(), 0)

    def test_create_practice_pack_rejects_unknown_question(self):
        response = self.client.post(
            "/api/resource/v1/practice-packs",
            {
                "title": "一次函数薄弱点强化训练",
                "target": "class",
                "target_ref_id": "class_8_3",
                "knowledge_point_ids": ["kp_math_8_function_linear"],
                "question_ids": ["bq_missing"],
                "created_by": "teacher_001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("question_ids", response.json()["data"])
        self.assertEqual(PracticePack.objects.count(), 0)

    def test_create_practice_pack_rejects_unapproved_question(self):
        response = self.client.post(
            "/api/resource/v1/practice-packs",
            {
                "title": "一次函数薄弱点强化训练",
                "target": "student",
                "target_ref_id": "student_001",
                "knowledge_point_ids": ["kp_math_8_function_linear"],
                "question_ids": ["bq_pack_draft"],
                "created_by": "teacher_001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("question_ids", response.json()["data"])
        self.assertEqual(PracticePack.objects.count(), 0)

    def test_create_practice_pack_rejects_version_mismatched_question(self):
        versioned_linear_function = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质新版",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
            version="2027.1",
        )
        self._create_question(
            bank_question_id="bq_pack_2027",
            knowledge_points=[versioned_linear_function],
            knowledge_point_version="2027.1",
        )

        response = self.client.post(
            "/api/resource/v1/practice-packs",
            {
                "title": "一次函数薄弱点强化训练",
                "target": "class",
                "target_ref_id": "class_8_3",
                "knowledge_point_ids": ["kp_math_8_function_linear"],
                "question_ids": ["bq_pack_2027"],
                "created_by": "teacher_001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("question_ids", response.json()["data"])
        self.assertEqual(PracticePack.objects.count(), 0)

    def _create_question(
        self,
        bank_question_id,
        knowledge_points,
        audit_status=QuestionBankItem.AuditStatus.APPROVED,
        knowledge_point_version=KnowledgePoint.DEFAULT_VERSION,
    ):
        question = QuestionBankItem.objects.create(
            bank_question_id=bank_question_id,
            source=QuestionBankItem.Source.SCHOOL_BANK,
            content_html=f"<p>{bank_question_id} 题干。</p>",
            answer_html="<p>答案。</p>",
            analysis_html="<p>解析。</p>",
            question_type="解答题",
            difficulty=0.45,
            audit_status=audit_status,
            knowledge_point_version=knowledge_point_version,
        )
        question.knowledge_points.set(knowledge_points)
        return question


class LoadQuestionBankCommandTests(TestCase):
    def test_load_question_bank_is_idempotent(self):
        call_command("load_knowledge_points", stdout=StringIO())

        first_stdout = StringIO()
        call_command("load_question_bank", stdout=first_stdout)

        self.assertEqual(QuestionBankItem.objects.count(), 5)
        self.assertIn("5 created", first_stdout.getvalue())

        second_stdout = StringIO()
        call_command("load_question_bank", stdout=second_stdout)

        self.assertEqual(QuestionBankItem.objects.count(), 5)
        self.assertIn("5 updated", second_stdout.getvalue())

    def test_load_question_bank_rejects_unknown_knowledge_point(self):
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "invalid_question_bank.json"
            source.write_text(
                json.dumps(
                    {
                        "source": "school_bank",
                        "items": [
                            {
                                "bank_question_id": "bq_invalid",
                                "content_html": "<p>题干。</p>",
                                "answer_html": "<p>答案。</p>",
                                "analysis_html": "<p>解析。</p>",
                                "knowledge_point_ids": ["kp_missing"],
                                "question_type": "填空题",
                                "difficulty": 0.3,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "unknown knowledge point ids"):
                call_command("load_question_bank", source=str(source), stdout=StringIO())
