import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.exceptions import AIServiceUnavailableError
from resources.models import KnowledgePoint, QuestionBankItem

from .models import (
    ExplanationInteraction,
    PracticeAnswer,
    StudentMastery,
    WrongQuestion,
)
from .p1_client import P1HTTPClient
from .services import record_practice_answer


class StudentApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir.name)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        cls._media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.student_id = "stu_001"
        self.student_headers = {"HTTP_X_STUDENT_ID": self.student_id}
        self.triangle_sides = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_triangle_side_relation",
            code="MATH.8.GEO.002",
            name="三角形三边关系",
            parent_id="kp_math_junior_geometry",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["图形与几何", "三角形", "三角形三边关系"],
        )
        self.linear_function = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_8_function_linear",
            code="MATH.8.FUNC.001",
            name="一次函数图像与性质",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["数与代数", "函数", "一次函数图像与性质"],
        )
        self.triangle_question = self._create_question(
            "bq_triangle_sides",
            [self.triangle_sides],
            difficulty=0.3,
        )
        self.unrelated_question = self._create_question(
            "bq_linear",
            [self.linear_function],
            difficulty=0.5,
        )
        self.rejected_question = self._create_question(
            "bq_triangle_rejected",
            [self.triangle_sides],
            difficulty=0.25,
            audit_status=QuestionBankItem.AuditStatus.REJECTED,
        )

    def test_student_endpoints_require_student_identity(self):
        response = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "UNAUTHORIZED")

        response = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            HTTP_X_TEACHER_ID="teacher_001",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "FORBIDDEN")

    def test_student_id_must_match_header(self):
        payload = self._upload_payload()
        payload["student_id"] = "stu_other"
        response = self.client.post(
            "/api/student/v1/wrong-questions",
            payload,
            format="multipart",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "FORBIDDEN")

    def test_upload_poll_and_confirm_wrong_question(self):
        upload_response = self._upload_wrong_question()
        self.assertEqual(upload_response.status_code, 200)
        upload_data = upload_response.json()["data"]
        self.assertEqual(upload_data["status"], WrongQuestion.Status.RECOGNIZING)
        self.assertTrue(upload_data["recognition_job_id"].startswith("job_wrong_"))

        detail_response = self.client.get(
            f"/api/student/v1/wrong-questions/{upload_data['wrong_question_id']}",
            **self.student_headers,
        )
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()["data"]
        self.assertEqual(detail["status"], WrongQuestion.Status.RECOGNIZED)
        self.assertIn("不能围成三角形", detail["question"]["stem_html"])
        self.assertEqual(
            detail["knowledge_candidates"][0]["knowledge_point_id"],
            self.triangle_sides.knowledge_point_id,
        )
        self.assertNotIn("file", detail)

        confirm_response = self.client.put(
            f"/api/student/v1/wrong-questions/{upload_data['wrong_question_id']}/confirm",
            {
                "stem_html": "<p>修正后的三角形三边关系题。</p>",
                "question_type": "选择题",
                "knowledge_point_ids": [self.triangle_sides.knowledge_point_id],
            },
            format="json",
            **self.student_headers,
        )
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(
            confirm_response.json()["data"]["status"],
            WrongQuestion.Status.CONFIRMED,
        )
        wrong_question = WrongQuestion.objects.get(
            wrong_question_id=upload_data["wrong_question_id"]
        )
        self.assertEqual(
            wrong_question.question["stem_html"],
            "<p>修正后的三角形三边关系题。</p>",
        )
        self.assertEqual(
            list(
                wrong_question.confirmed_knowledge_points.values_list(
                    "knowledge_point_id", flat=True
                )
            ),
            [self.triangle_sides.knowledge_point_id],
        )

    def test_wrong_question_is_scoped_by_student_and_tenant(self):
        wrong_question = self._create_confirmed_wrong_question()
        other_student_response = self.client.get(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}",
            HTTP_X_STUDENT_ID="stu_other",
        )
        other_tenant_response = self.client.get(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}",
            HTTP_X_STUDENT_ID=self.student_id,
            HTTP_X_TENANT_ID="school_other",
        )
        self.assertEqual(other_student_response.status_code, 404)
        self.assertEqual(other_tenant_response.status_code, 404)

    def test_wrong_question_upload_is_idempotent(self):
        headers = {
            **self.student_headers,
            "HTTP_IDEMPOTENCY_KEY": "upload-001",
        }
        first = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            **headers,
        )
        second = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            **headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.json()["data"]["wrong_question_id"],
            second.json()["data"]["wrong_question_id"],
        )
        self.assertEqual(WrongQuestion.objects.count(), 1)

        different_payload = self._upload_payload()
        different_payload["grade"] = "9"
        conflict = self.client.post(
            "/api/student/v1/wrong-questions",
            different_payload,
            format="multipart",
            **headers,
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "CONFLICT")

    @patch("students.views.get_p1_client")
    def test_p1_receives_a_working_short_lived_file_url(self, get_client):
        p1_client = get_client.return_value
        p1_client.recognize_wrong_question.return_value = {
            "job_id": "job_file_url_001"
        }

        upload = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            **self.student_headers,
        )

        self.assertEqual(upload.status_code, 200)
        file_payload = p1_client.recognize_wrong_question.call_args.kwargs["file"]
        file_path = urlsplit(file_payload["storage_uri"]).path
        downloaded = self.client.get(file_path)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(
            b"".join(downloaded.streaming_content),
            b"\x89PNG\r\n\x1a\nmock-image",
        )

        tampered = self.client.get(f"{file_path}tampered")
        self.assertEqual(tampered.status_code, 404)

    @patch("students.views.get_p1_client")
    def test_failed_recognition_is_recorded_and_same_upload_can_retry(
        self,
        get_client,
    ):
        p1_client = get_client.return_value
        p1_client.recognize_wrong_question.side_effect = AIServiceUnavailableError(
            "P1 unavailable"
        )
        headers = {
            **self.student_headers,
            "HTTP_IDEMPOTENCY_KEY": "upload-retry-001",
        }

        failed = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            **headers,
        )

        self.assertEqual(failed.status_code, 503)
        wrong_question = WrongQuestion.objects.get()
        self.assertEqual(
            wrong_question.status,
            WrongQuestion.Status.RECOGNITION_FAILED,
        )
        self.assertIn("P1 unavailable", wrong_question.recognition_error)

        p1_client.recognize_wrong_question.side_effect = None
        p1_client.recognize_wrong_question.return_value = {"job_id": "job_retry_001"}
        retried = self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            **headers,
        )

        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["data"]["status"], "recognizing")
        self.assertEqual(
            retried.json()["data"]["recognition_job_id"],
            "job_retry_001",
        )
        self.assertEqual(WrongQuestion.objects.count(), 1)

    @patch("students.views.get_p1_client")
    def test_failed_async_job_moves_wrong_question_to_failed_state(self, get_client):
        wrong_question = WrongQuestion.objects.create(
            wrong_question_id="wq_failed_job",
            student_id=self.student_id,
            subject="math",
            grade="8",
            file="students/wrong_questions/failed.png",
            recognition_job_id="job_failed_001",
            status=WrongQuestion.Status.RECOGNIZING,
        )
        get_client.return_value.get_job.return_value = {
            "job_id": "job_failed_001",
            "status": "failed",
        }

        response = self.client.get(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}",
            **self.student_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["status"],
            WrongQuestion.Status.RECOGNITION_FAILED,
        )
        self.assertIn("failed", response.json()["data"]["recognition_error"])

    @patch("students.views.get_p1_client")
    def test_stale_failed_poll_cannot_overwrite_newer_status(self, get_client):
        wrong_question = WrongQuestion.objects.create(
            wrong_question_id="wq_stale_failed_poll",
            student_id=self.student_id,
            subject="math",
            grade="8",
            file="students/wrong_questions/stale.png",
            recognition_job_id="job_stale_001",
            status=WrongQuestion.Status.RECOGNIZING,
        )

        def finish_elsewhere(*args, **kwargs):
            del args, kwargs
            WrongQuestion.objects.filter(pk=wrong_question.pk).update(
                status=WrongQuestion.Status.MASTERED
            )
            return {"job_id": "job_stale_001", "status": "failed"}

        get_client.return_value.get_job.side_effect = finish_elsewhere
        response = self.client.get(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}",
            **self.student_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "mastered")

    @override_settings(P1_RECOGNITION_START_GRACE_SECONDS=30)
    def test_recognition_without_job_id_only_fails_after_start_grace(self):
        wrong_question = WrongQuestion.objects.create(
            wrong_question_id="wq_starting_without_job",
            student_id=self.student_id,
            subject="math",
            grade="8",
            file="students/wrong_questions/starting.png",
            status=WrongQuestion.Status.RECOGNIZING,
        )

        starting = self.client.get(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}",
            **self.student_headers,
        )
        self.assertEqual(starting.status_code, 200)
        self.assertEqual(starting.json()["data"]["status"], "recognizing")

        WrongQuestion.objects.filter(pk=wrong_question.pk).update(
            updated_at=timezone.now() - timedelta(seconds=31)
        )
        stale = self.client.get(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}",
            **self.student_headers,
        )
        self.assertEqual(stale.status_code, 200)
        self.assertEqual(stale.json()["data"]["status"], "recognition_failed")

    def test_upload_rejects_invalid_type_and_size(self):
        invalid_type = self._upload_payload(
            SimpleUploadedFile("wrong.txt", b"not an image", content_type="text/plain")
        )
        response = self.client.post(
            "/api/student/v1/wrong-questions",
            invalid_type,
            format="multipart",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["code"], "UNSUPPORTED_FILE_TYPE")

        misleading_extension = self._upload_payload(
            SimpleUploadedFile(
                "wrong.html",
                b"\x89PNG\r\n\x1a\nmock-image",
                content_type="image/png",
            )
        )
        response = self.client.post(
            "/api/student/v1/wrong-questions",
            misleading_extension,
            format="multipart",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["code"], "UNSUPPORTED_FILE_TYPE")

        forged_png = self._upload_payload(
            SimpleUploadedFile(
                "wrong.png",
                b"not-really-a-png",
                content_type="image/png",
            )
        )
        response = self.client.post(
            "/api/student/v1/wrong-questions",
            forged_png,
            format="multipart",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["code"], "UNSUPPORTED_FILE_TYPE")

        with override_settings(WRONG_QUESTION_MAX_FILE_SIZE=4):
            response = self.client.post(
                "/api/student/v1/wrong-questions",
                self._upload_payload(),
                format="multipart",
                **self.student_headers,
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "FILE_TOO_LARGE")

    def test_confirm_rejects_invalid_state_and_unknown_knowledge_point(self):
        upload = self._upload_wrong_question().json()["data"]
        invalid_state = self.client.put(
            f"/api/student/v1/wrong-questions/{upload['wrong_question_id']}/confirm",
            {
                "stem_html": "<p>题干</p>",
                "knowledge_point_ids": [self.triangle_sides.knowledge_point_id],
            },
            format="json",
            **self.student_headers,
        )
        self.assertEqual(invalid_state.status_code, 409)
        self.assertEqual(invalid_state.json()["code"], "CONFLICT")

        self.client.get(
            f"/api/student/v1/wrong-questions/{upload['wrong_question_id']}",
            **self.student_headers,
        )
        unknown_point = self.client.put(
            f"/api/student/v1/wrong-questions/{upload['wrong_question_id']}/confirm",
            {
                "stem_html": "<p>题干</p>",
                "knowledge_point_ids": ["kp_missing"],
            },
            format="json",
            **self.student_headers,
        )
        self.assertEqual(unknown_point.status_code, 400)
        self.assertEqual(unknown_point.json()["code"], "VALIDATION_ERROR")

        grade_nine_point = KnowledgePoint.objects.create(
            knowledge_point_id="kp_math_9_incompatible",
            code="MATH.9.INCOMPATIBLE.001",
            name="九年级知识点",
            subject="math",
            stage="junior_middle_school",
            grade_range=["9"],
            path=["九年级知识点"],
        )
        incompatible_point = self.client.put(
            f"/api/student/v1/wrong-questions/{upload['wrong_question_id']}/confirm",
            {
                "stem_html": "<p>题干</p>",
                "knowledge_point_ids": [grade_nine_point.knowledge_point_id],
            },
            format="json",
            **self.student_headers,
        )
        self.assertEqual(incompatible_point.status_code, 400)
        self.assertEqual(incompatible_point.json()["code"], "VALIDATION_ERROR")

    def test_guided_explanation_moves_to_learning_and_logs_interaction(self):
        wrong_question = self._create_confirmed_wrong_question()
        response = self.client.post(
            f"/api/student/v1/wrong-questions/{wrong_question.wrong_question_id}/explanation/next",
            {
                "current_step_index": 0,
                "student_input": "我不知道如何判断。",
                "mode": "hint",
            },
            format="json",
            HTTP_X_REQUEST_ID="req_explanation_001",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["step_index"], 1)
        self.assertFalse(response.json()["data"]["can_show_full_answer"])
        wrong_question.refresh_from_db()
        self.assertEqual(wrong_question.status, WrongQuestion.Status.LEARNING)
        interaction = ExplanationInteraction.objects.get()
        self.assertEqual(interaction.request_id, "req_explanation_001")
        self.assertEqual(interaction.mode, ExplanationInteraction.Mode.HINT)

    def test_recommendations_use_confirmed_points_and_hide_answers(self):
        self._create_confirmed_wrong_question()
        response = self.client.get(
            "/api/student/v1/practice/recommendations",
            {"student_id": self.student_id, "limit": 5},
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()["data"]["items"]
        self.assertEqual(
            [item["bank_question_id"] for item in items],
            [self.triangle_question.bank_question_id],
        )
        self.assertNotIn("answer_html", items[0])
        self.assertNotIn("analysis_html", items[0])
        self.assertNotIn(self.rejected_question.bank_question_id, str(items))

    def test_recommendations_fall_back_to_unseen_approved_same_version(self):
        self._create_confirmed_wrong_question()
        self.triangle_question.audit_status = QuestionBankItem.AuditStatus.REJECTED
        self.triangle_question.save(update_fields=["audit_status", "updated_at"])
        unseen_fallback = self._create_question(
            "bq_linear_unseen",
            [self.linear_function],
            difficulty=0.45,
        )
        PracticeAnswer.objects.create(
            answer_record_id="ans_linear_seen",
            student_id=self.student_id,
            question=self.unrelated_question,
            answer_text="A",
            is_correct=True,
        )

        response = self.client.get(
            "/api/student/v1/practice/recommendations",
            {"student_id": self.student_id, "limit": 5},
            **self.student_headers,
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["data"]["items"]
        self.assertEqual(
            [item["bank_question_id"] for item in items],
            [
                unseen_fallback.bank_question_id,
                self.unrelated_question.bank_question_id,
            ],
        )
        self.assertTrue(
            all(item["knowledge_point_version"] == "2026.1" for item in items)
        )
        self.assertNotIn(self.rejected_question.bank_question_id, str(items))

    def test_answer_updates_mastery_and_idempotency_prevents_double_update(self):
        headers = {
            **self.student_headers,
            "HTTP_IDEMPOTENCY_KEY": "answer-001",
        }
        payload = {
            "student_id": self.student_id,
            "bank_question_id": self.triangle_question.bank_question_id,
            "answer_text": "B",
            "is_correct": True,
            "used_seconds": 30,
        }
        first = self.client.post(
            "/api/student/v1/practice/answers",
            payload,
            format="json",
            **headers,
        )
        replay = self.client.post(
            "/api/student/v1/practice/answers",
            payload,
            format="json",
            **headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            first.json()["data"]["answer_record_id"],
            replay.json()["data"]["answer_record_id"],
        )
        mastery = StudentMastery.objects.get(
            student_id=self.student_id,
            knowledge_point=self.triangle_sides,
        )
        self.assertEqual(mastery.mastery_rate, 0.55)
        self.assertEqual(PracticeAnswer.objects.count(), 1)

        conflicting_replay = self.client.post(
            "/api/student/v1/practice/answers",
            {**payload, "answer_text": "A"},
            format="json",
            **headers,
        )
        self.assertEqual(conflicting_replay.status_code, 409)
        self.assertEqual(conflicting_replay.json()["code"], "CONFLICT")

        incorrect = self.client.post(
            "/api/student/v1/practice/answers",
            {**payload, "is_correct": False},
            format="json",
            **self.student_headers,
        )
        self.assertEqual(incorrect.status_code, 200)
        mastery.refresh_from_db()
        self.assertEqual(mastery.mastery_rate, 0.47)

        replay_after_other_answer = self.client.post(
            "/api/student/v1/practice/answers",
            payload,
            format="json",
            **headers,
        )
        self.assertEqual(replay_after_other_answer.status_code, 200)
        self.assertEqual(
            replay_after_other_answer.json()["data"]["updated_mastery"],
            first.json()["data"]["updated_mastery"],
        )

    def test_mastery_is_clamped_and_can_mark_wrong_question_mastered(self):
        wrong_question = self._create_confirmed_wrong_question(
            status=WrongQuestion.Status.LEARNING
        )
        mastery = StudentMastery.objects.create(
            student_id=self.student_id,
            knowledge_point=self.triangle_sides,
            mastery_rate=0.98,
        )
        response = self.client.post(
            "/api/student/v1/practice/answers",
            {
                "student_id": self.student_id,
                "bank_question_id": self.triangle_question.bank_question_id,
                "answer_text": "B",
                "is_correct": True,
                "used_seconds": 20,
            },
            format="json",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 200)
        mastery.refresh_from_db()
        wrong_question.refresh_from_db()
        self.assertEqual(mastery.mastery_rate, 1.0)
        self.assertEqual(wrong_question.status, WrongQuestion.Status.MASTERED)

        mastery.mastery_rate = 0.02
        mastery.save()
        self.client.post(
            "/api/student/v1/practice/answers",
            {
                "student_id": self.student_id,
                "bank_question_id": self.triangle_question.bank_question_id,
                "answer_text": "A",
                "is_correct": False,
                "used_seconds": 20,
            },
            format="json",
            **self.student_headers,
        )
        mastery.refresh_from_db()
        self.assertEqual(mastery.mastery_rate, 0.0)

    def test_answers_reject_unapproved_question(self):
        response = self.client.post(
            "/api/student/v1/practice/answers",
            {
                "student_id": self.student_id,
                "bank_question_id": self.rejected_question.bank_question_id,
                "answer_text": "B",
                "is_correct": True,
                "used_seconds": 10,
            },
            format="json",
            **self.student_headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "NOT_FOUND")

    def _upload_wrong_question(self, **headers):
        return self.client.post(
            "/api/student/v1/wrong-questions",
            self._upload_payload(),
            format="multipart",
            **{**self.student_headers, **headers},
        )

    def _upload_payload(self, image=None):
        return {
            "student_id": self.student_id,
            "subject": "math",
            "grade": "8",
            "image": image
            or SimpleUploadedFile(
                "wrong.png",
                b"\x89PNG\r\n\x1a\nmock-image",
                content_type="image/png",
            ),
        }

    def _create_confirmed_wrong_question(self, status=WrongQuestion.Status.CONFIRMED):
        wrong_question = WrongQuestion.objects.create(
            wrong_question_id=f"wq_{WrongQuestion.objects.count() + 1}",
            student_id=self.student_id,
            subject="math",
            grade="8",
            file="students/wrong_questions/test.png",
            status=status,
            question={
                "stem_html": "<p>三角形三边关系测试题。</p>",
                "question_type": "选择题",
                "images": [],
            },
        )
        wrong_question.confirmed_knowledge_points.add(self.triangle_sides)
        return wrong_question

    def _create_question(
        self,
        bank_question_id,
        knowledge_points,
        *,
        difficulty,
        audit_status=QuestionBankItem.AuditStatus.APPROVED,
    ):
        question = QuestionBankItem.objects.create(
            bank_question_id=bank_question_id,
            source=QuestionBankItem.Source.SCHOOL_BANK,
            content_html=f"<p>{bank_question_id} 题干</p>",
            answer_html="<p>答案</p>",
            analysis_html="<p>解析</p>",
            question_type="选择题",
            difficulty=difficulty,
            images=[],
            audit_status=audit_status,
        )
        question.knowledge_points.set(knowledge_points)
        return question


class PracticeAnswerConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.knowledge_point = KnowledgePoint.objects.create(
            knowledge_point_id="kp_concurrency",
            code="MATH.CONCURRENCY.001",
            name="并发测试知识点",
            subject="math",
            stage="junior_middle_school",
            grade_range=["8"],
            path=["并发测试知识点"],
        )
        self.question = QuestionBankItem.objects.create(
            bank_question_id="bq_concurrency",
            source=QuestionBankItem.Source.SCHOOL_BANK,
            content_html="<p>并发测试题。</p>",
            answer_html="<p>A</p>",
            analysis_html="<p>测试解析。</p>",
            question_type="选择题",
            difficulty=0.5,
            audit_status=QuestionBankItem.AuditStatus.APPROVED,
        )
        self.question.knowledge_points.add(self.knowledge_point)

    def test_concurrent_idempotent_answers_create_and_score_once(self):
        barrier = threading.Barrier(2)

        def submit():
            close_old_connections()
            try:
                question = QuestionBankItem.objects.get(
                    bank_question_id=self.question.bank_question_id
                )
                barrier.wait(timeout=5)
                answer, mastery, created = record_practice_answer(
                    tenant_id="school_001",
                    student_id="stu_concurrency",
                    question=question,
                    answer_text="A",
                    is_correct=True,
                    used_seconds=10,
                    idempotency_key="answer-concurrency-001",
                )
                return answer.answer_record_id, mastery, created
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit(), range(2)))

        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(sorted(result[2] for result in results), [False, True])
        self.assertEqual(PracticeAnswer.objects.count(), 1)
        self.assertEqual(StudentMastery.objects.get().mastery_rate, 0.55)


class P1HTTPClientTests(TestCase):
    @patch("students.p1_client.urlopen")
    def test_http_client_forwards_request_id_and_unwraps_response(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"code": "OK", "data": {"job_id": "job_001"}}
        ).encode()
        mock_urlopen.return_value = response
        client = P1HTTPClient("http://p1.test/api/ai/v1", timeout_seconds=3)

        result = client.recognize_wrong_question(
            student_id="stu_001",
            file={"file_id": "file_001"},
            options={"subject": "math"},
            request_id="req_001",
            tenant_id="school_001",
        )

        self.assertEqual(result, {"job_id": "job_001"})
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-request-id"), "req_001")
        self.assertEqual(request.get_header("X-tenant-id"), "school_001")
        self.assertEqual(request.get_header("X-service-id"), "p3-service")
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 3)

        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "code": "OK",
                "data": {
                    "job_id": "job_001",
                    "status": "running",
                    "progress": 50,
                },
            }
        ).encode()
        job = client.get_job("job_001", request_id="req_002")
        self.assertEqual(job["status"], "running")
        job_request = mock_urlopen.call_args.args[0]
        self.assertEqual(job_request.get_header("X-request-id"), "req_002")

    @patch("students.p1_client.urlopen")
    def test_http_client_normalizes_success_status_aliases(self, mock_urlopen):
        response = MagicMock()
        mock_urlopen.return_value = response
        client = P1HTTPClient("http://p1.test/api/ai/v1")

        for raw_status in ("completed", "success"):
            with self.subTest(endpoint="job", raw_status=raw_status):
                response.__enter__.return_value.read.return_value = json.dumps(
                    {
                        "code": "OK",
                        "data": {"job_id": "job_001", "status": raw_status},
                    }
                ).encode()
                self.assertEqual(client.get_job("job_001")["status"], "succeeded")

            with self.subTest(endpoint="result", raw_status=raw_status):
                wrapped_result = {"question": {"stem_html": "<p>题干</p>"}}
                response.__enter__.return_value.read.return_value = json.dumps(
                    {
                        "code": "OK",
                        "data": {
                            "status": raw_status,
                            "result": wrapped_result,
                        },
                    }
                ).encode()
                self.assertEqual(
                    client.get_wrong_question_result("job_001"),
                    {"status": "succeeded", "result": wrapped_result},
                )

    @patch("students.p1_client.urlopen")
    def test_http_client_rejects_oversized_job_id(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"code": "OK", "data": {"job_id": "j" * 129}}
        ).encode()
        mock_urlopen.return_value = response

        client = P1HTTPClient("http://p1.test/api/ai/v1")
        with self.assertRaises(AIServiceUnavailableError):
            client.recognize_wrong_question(
                student_id="stu_001",
                file={"file_id": "file_001"},
                options={"subject": "math"},
            )

    @patch("students.p1_client.urlopen")
    def test_http_client_rejects_invalid_result_status_type(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"code": "OK", "data": {"status": [], "result": {}}}
        ).encode()
        mock_urlopen.return_value = response

        client = P1HTTPClient("http://p1.test/api/ai/v1")
        with self.assertRaises(AIServiceUnavailableError):
            client.get_wrong_question_result("job_001")

    @patch("students.p1_client.urlopen", side_effect=TimeoutError("timeout"))
    def test_http_client_maps_network_failure(self, mock_urlopen):
        del mock_urlopen
        client = P1HTTPClient("http://p1.test/api/ai/v1")
        with self.assertRaises(AIServiceUnavailableError):
            client.get_wrong_question_result("job_001")
