import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from core.authentication import MockHeaderAuthentication
from core.exceptions import (
    AIResultNeedsReviewError,
    AIServiceUnavailableError,
    ConflictError,
)
from core.permissions import IsStudent
from core.responses import api_response
from resources.models import QuestionBankItem
from resources.services import get_knowledge_points_by_public_ids

from .models import ExplanationInteraction, WrongQuestion
from .p1_client import get_p1_client
from .serializers import (
    ExplanationNextSerializer,
    PracticeAnswerRequestSerializer,
    PracticeRecommendationQuerySerializer,
    WrongQuestionConfirmSerializer,
    WrongQuestionUploadSerializer,
)
from .services import (
    generate_interaction_id,
    generate_wrong_question_id,
    get_owned_wrong_question,
    recommend_questions,
    record_practice_answer,
    serialize_wrong_question,
)


WRONG_QUESTION_FILE_TOKEN_SALT = "students.wrong-question-file.v1"


class StudentAPIView(APIView):
    authentication_classes = [MockHeaderAuthentication]
    permission_classes = [IsStudent]

    @staticmethod
    def validate_student_id(request, student_id):
        if student_id != request.user.identifier:
            raise PermissionDenied("student_id must match X-Student-Id")

    @staticmethod
    def get_idempotency_key(request):
        value = request.headers.get("Idempotency-Key", "").strip()
        if len(value) > 128:
            raise ValidationError(
                {"Idempotency-Key": ["must contain at most 128 characters"]}
            )
        return value


class WrongQuestionFileView(APIView):
    """Serve a short-lived signed file URL to an asynchronous P1 worker."""

    authentication_classes = []
    permission_classes = []

    @extend_schema(exclude=True)
    def get(self, request, token):
        del request
        try:
            payload = signing.loads(
                token,
                salt=WRONG_QUESTION_FILE_TOKEN_SALT,
                max_age=settings.P1_FILE_URL_TTL_SECONDS,
            )
        except signing.BadSignature as exc:
            raise Http404("wrong-question file not found") from exc
        if not isinstance(payload, dict):
            raise Http404("wrong-question file not found")
        try:
            wrong_question = WrongQuestion.objects.get(
                wrong_question_id=payload.get("wrong_question_id"),
                tenant_id=payload.get("tenant_id"),
            )
        except WrongQuestion.DoesNotExist as exc:
            raise Http404("wrong-question file not found") from exc
        try:
            file_handle = wrong_question.file.open("rb")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise Http404("wrong-question file not found") from exc

        content_type = (
            mimetypes.guess_type(wrong_question.file.name)[0]
            or "application/octet-stream"
        )
        return FileResponse(
            file_handle,
            content_type=content_type,
            filename=f"{wrong_question.wrong_question_id}{Path(wrong_question.file.name).suffix}",
        )


class WrongQuestionUploadView(StudentAPIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                OpenApiTypes.STR,
                OpenApiParameter.HEADER,
                required=False,
                description="重复上传时返回同一错题，不重复创建识别任务。",
            )
        ],
        request=WrongQuestionUploadSerializer,
        responses=inline_serializer(
            name="WrongQuestionUploadResponse",
            fields={
                "request_id": serializers.CharField(),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="WrongQuestionUploadData",
                    fields={
                        "wrong_question_id": serializers.CharField(),
                        "recognition_job_id": serializers.CharField(allow_null=True),
                        "status": serializers.CharField(),
                    },
                ),
            },
        ),
    )
    def post(self, request):
        request_serializer = WrongQuestionUploadSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data
        self.validate_student_id(request, payload["student_id"])
        idempotency_key = self.get_idempotency_key(request)

        uploaded_file = payload["image"]
        file_digest = self._hash_upload(uploaded_file)
        idempotency_fingerprint = self._upload_fingerprint(
            payload=payload,
            file_digest=file_digest,
        )

        wrong_question = None
        if idempotency_key:
            wrong_question = WrongQuestion.objects.filter(
                tenant_id=request.user.tenant_id,
                student_id=request.user.identifier,
                idempotency_key=idempotency_key,
            ).first()
            self._validate_idempotency_replay(
                wrong_question,
                idempotency_fingerprint,
            )

        created = False
        if wrong_question is None:
            candidate = WrongQuestion(
                wrong_question_id=generate_wrong_question_id(),
                tenant_id=request.user.tenant_id,
                student_id=request.user.identifier,
                subject=payload["subject"],
                grade=payload["grade"],
                file=uploaded_file,
                status=WrongQuestion.Status.UPLOADED,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=idempotency_fingerprint,
            )
            try:
                with transaction.atomic():
                    candidate.save()
            except IntegrityError:
                # FileField writes before the database insert. Remove the losing
                # race's opaque file and return the row created by the winner.
                if candidate.file.name:
                    candidate.file.storage.delete(candidate.file.name)
                if not idempotency_key:
                    raise
                wrong_question = WrongQuestion.objects.filter(
                    tenant_id=request.user.tenant_id,
                    student_id=request.user.identifier,
                    idempotency_key=idempotency_key,
                ).first()
                if wrong_question is None:
                    raise
                self._validate_idempotency_replay(
                    wrong_question,
                    idempotency_fingerprint,
                )
            else:
                wrong_question = candidate
                created = True

        if created or wrong_question.status == WrongQuestion.Status.RECOGNITION_FAILED:
            self._start_recognition(
                request=request,
                wrong_question=wrong_question,
                original_file=uploaded_file,
                file_digest=file_digest,
            )

        return api_response(
            request,
            data={
                "wrong_question_id": wrong_question.wrong_question_id,
                "recognition_job_id": wrong_question.recognition_job_id,
                "status": wrong_question.status,
            },
        )

    @staticmethod
    def _hash_upload(uploaded_file):
        digest = hashlib.sha256()
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
        uploaded_file.seek(0)
        return digest.hexdigest()

    @staticmethod
    def _upload_fingerprint(*, payload, file_digest):
        canonical_payload = {
            "subject": payload["subject"],
            "grade": payload["grade"],
            "file_name": Path(payload["image"].name).name,
            "mime_type": getattr(payload["image"], "content_type", ""),
            "size_bytes": payload["image"].size,
            "sha256": file_digest,
        }
        encoded = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_idempotency_replay(wrong_question, fingerprint):
        if (
            wrong_question is not None
            and wrong_question.idempotency_fingerprint
            and wrong_question.idempotency_fingerprint != fingerprint
        ):
            raise ConflictError(
                "Idempotency-Key has already been used with a different upload"
            )

    @staticmethod
    def _start_recognition(
        *,
        request,
        wrong_question,
        original_file,
        file_digest,
    ):
        started_at = timezone.now()
        claimed = WrongQuestion.objects.filter(
            pk=wrong_question.pk,
            status__in=[
                WrongQuestion.Status.UPLOADED,
                WrongQuestion.Status.RECOGNITION_FAILED,
            ],
        ).update(
            status=WrongQuestion.Status.RECOGNIZING,
            recognition_job_id=None,
            recognition_error="",
            updated_at=started_at,
        )
        if not claimed:
            wrong_question.refresh_from_db()
            return

        file_object = {
            "file_id": f"file_{wrong_question.wrong_question_id}",
            "file_name": Path(original_file.name).name,
            "mime_type": getattr(original_file, "content_type", ""),
            "size_bytes": original_file.size,
            "storage_uri": WrongQuestionUploadView._signed_file_uri(
                request,
                wrong_question,
            ),
            "sha256": file_digest,
        }
        try:
            response = get_p1_client().recognize_wrong_question(
                student_id=wrong_question.student_id,
                file=file_object,
                options={
                    "subject": wrong_question.subject,
                    "grade": wrong_question.grade,
                    "detect_handwriting": True,
                },
                request_id=getattr(request, "request_id", None),
                tenant_id=wrong_question.tenant_id,
            )
        except (AIServiceUnavailableError, ValueError) as exc:
            WrongQuestion.objects.filter(
                pk=wrong_question.pk,
                status=WrongQuestion.Status.RECOGNIZING,
                recognition_job_id__isnull=True,
                updated_at=started_at,
            ).update(
                status=WrongQuestion.Status.RECOGNITION_FAILED,
                recognition_error=str(exc),
                updated_at=timezone.now(),
            )
            wrong_question.refresh_from_db()
            if isinstance(exc, AIServiceUnavailableError):
                raise
            raise AIServiceUnavailableError(
                "AI service client configuration is invalid"
            ) from exc
        WrongQuestion.objects.filter(
            pk=wrong_question.pk,
            status=WrongQuestion.Status.RECOGNIZING,
            recognition_job_id__isnull=True,
            updated_at=started_at,
        ).update(
            recognition_job_id=response["job_id"],
            recognition_error="",
            updated_at=timezone.now(),
        )
        wrong_question.refresh_from_db()

    @staticmethod
    def _signed_file_uri(request, wrong_question):
        token = signing.dumps(
            {
                "wrong_question_id": wrong_question.wrong_question_id,
                "tenant_id": wrong_question.tenant_id,
            },
            salt=WRONG_QUESTION_FILE_TOKEN_SALT,
            compress=True,
        )
        path = f"/api/student/v1/wrong-question-files/{quote(token, safe='')}"
        if settings.P1_FILE_BASE_URL:
            return f"{settings.P1_FILE_BASE_URL}{path}"
        return request.build_absolute_uri(path)


class WrongQuestionDetailView(StudentAPIView):
    @extend_schema(
        responses=inline_serializer(
            name="WrongQuestionDetailResponse",
            fields={
                "request_id": serializers.CharField(),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": serializers.DictField(),
            },
        )
    )
    def get(self, request, wrong_question_id):
        wrong_question = get_owned_wrong_question(
            wrong_question_id=wrong_question_id,
            tenant_id=request.user.tenant_id,
            student_id=request.user.identifier,
        )
        if wrong_question.status == WrongQuestion.Status.RECOGNIZING:
            self._refresh_recognition(request, wrong_question)
            wrong_question = get_owned_wrong_question(
                wrong_question_id=wrong_question_id,
                tenant_id=request.user.tenant_id,
                student_id=request.user.identifier,
            )
        return api_response(request, data=serialize_wrong_question(wrong_question))

    @staticmethod
    def _refresh_recognition(request, wrong_question):
        if not wrong_question.recognition_job_id:
            start_age_seconds = (
                timezone.now() - wrong_question.updated_at
            ).total_seconds()
            if start_age_seconds <= settings.P1_RECOGNITION_START_GRACE_SECONDS:
                return
            WrongQuestion.objects.filter(
                pk=wrong_question.pk,
                status=WrongQuestion.Status.RECOGNIZING,
                recognition_job_id__isnull=True,
            ).update(
                status=WrongQuestion.Status.RECOGNITION_FAILED,
                recognition_error="recognition job ID is missing",
                updated_at=timezone.now(),
            )
            return
        client = get_p1_client()
        request_id = getattr(request, "request_id", None)
        recognition_job_id = wrong_question.recognition_job_id
        job = client.get_job(
            recognition_job_id,
            request_id=request_id,
            tenant_id=wrong_question.tenant_id,
        )
        job_status = job.get("status")
        if job_status in {"queued", "running"}:
            return
        if job_status != "succeeded":
            WrongQuestion.objects.filter(
                pk=wrong_question.pk,
                status=WrongQuestion.Status.RECOGNIZING,
                recognition_job_id=recognition_job_id,
            ).update(
                status=WrongQuestion.Status.RECOGNITION_FAILED,
                recognition_error=f"recognition job ended with status {job_status}",
                updated_at=timezone.now(),
            )
            return

        response = client.get_wrong_question_result(
            recognition_job_id,
            request_id=request_id,
            tenant_id=wrong_question.tenant_id,
        )
        status = response.get("status")
        if status in {"queued", "running"}:
            return
        if status != "succeeded":
            WrongQuestion.objects.filter(
                pk=wrong_question.pk,
                status=WrongQuestion.Status.RECOGNIZING,
                recognition_job_id=recognition_job_id,
            ).update(
                status=WrongQuestion.Status.RECOGNITION_FAILED,
                recognition_error=f"recognition result ended with status {status}",
                updated_at=timezone.now(),
            )
            return

        result = response.get("result")
        if not isinstance(result, dict):
            WrongQuestion.objects.filter(
                pk=wrong_question.pk,
                status=WrongQuestion.Status.RECOGNIZING,
                recognition_job_id=recognition_job_id,
            ).update(
                status=WrongQuestion.Status.RECOGNITION_FAILED,
                recognition_error="recognition result is invalid",
                updated_at=timezone.now(),
            )
            raise AIServiceUnavailableError("recognition result is invalid")
        question = result.get("question")
        candidates = result.get("knowledge_candidates")
        if not isinstance(question, dict) or not isinstance(candidates, list):
            WrongQuestion.objects.filter(
                pk=wrong_question.pk,
                status=WrongQuestion.Status.RECOGNIZING,
                recognition_job_id=recognition_job_id,
            ).update(
                status=WrongQuestion.Status.RECOGNITION_FAILED,
                recognition_error="recognition result is invalid",
                updated_at=timezone.now(),
            )
            raise AIServiceUnavailableError("recognition result is invalid")

        WrongQuestion.objects.filter(
            pk=wrong_question.pk,
            status=WrongQuestion.Status.RECOGNIZING,
            recognition_job_id=recognition_job_id,
        ).update(
            question=question,
            knowledge_candidates=candidates,
            recognition_error="",
            status=WrongQuestion.Status.RECOGNIZED,
            updated_at=timezone.now(),
        )


class WrongQuestionConfirmView(StudentAPIView):
    @extend_schema(
        request=WrongQuestionConfirmSerializer,
        responses=inline_serializer(
            name="WrongQuestionConfirmResponse",
            fields={
                "request_id": serializers.CharField(),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="WrongQuestionConfirmData",
                    fields={
                        "wrong_question_id": serializers.CharField(),
                        "status": serializers.CharField(),
                    },
                ),
            },
        ),
    )
    def put(self, request, wrong_question_id):
        request_serializer = WrongQuestionConfirmSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data

        with transaction.atomic():
            try:
                wrong_question = WrongQuestion.objects.select_for_update().get(
                    wrong_question_id=wrong_question_id,
                    tenant_id=request.user.tenant_id,
                    student_id=request.user.identifier,
                )
            except WrongQuestion.DoesNotExist as exc:
                raise NotFound("wrong question not found") from exc
            if wrong_question.status not in {
                WrongQuestion.Status.RECOGNIZED,
                WrongQuestion.Status.CONFIRMED,
            }:
                raise ConflictError(
                    f"wrong question cannot be confirmed from status {wrong_question.status}"
                )

            knowledge_point_map, missing_ids = get_knowledge_points_by_public_ids(
                payload["knowledge_point_ids"],
                wrong_question.knowledge_point_version,
            )
            disabled_ids = [
                item_id
                for item_id, item in knowledge_point_map.items()
                if not item.enabled
            ]
            incompatible_ids = [
                item_id
                for item_id, item in knowledge_point_map.items()
                if item.subject != wrong_question.subject
                or (
                    item.grade_range
                    and str(wrong_question.grade)
                    not in {str(grade) for grade in item.grade_range}
                )
            ]
            invalid_ids = list(
                dict.fromkeys([*missing_ids, *disabled_ids, *incompatible_ids])
            )
            if invalid_ids:
                raise ValidationError(
                    {
                        "knowledge_point_ids": [
                            "Unknown, disabled, or subject/grade-incompatible "
                            "knowledge points for version "
                            f"{wrong_question.knowledge_point_version}: "
                            f"{', '.join(invalid_ids)}"
                        ]
                    }
                )

            question = dict(wrong_question.question)
            question["stem_html"] = payload["stem_html"]
            if "question_type" in payload:
                question["question_type"] = payload["question_type"]
            wrong_question.question = question
            wrong_question.status = WrongQuestion.Status.CONFIRMED
            wrong_question.save(update_fields=["question", "status", "updated_at"])
            unique_ids = list(dict.fromkeys(payload["knowledge_point_ids"]))
            wrong_question.confirmed_knowledge_points.set(
                [knowledge_point_map[item_id] for item_id in unique_ids]
            )

        return api_response(
            request,
            data={
                "wrong_question_id": wrong_question.wrong_question_id,
                "status": wrong_question.status,
            },
        )


class ExplanationNextView(StudentAPIView):
    @extend_schema(
        request=ExplanationNextSerializer,
        responses=inline_serializer(
            name="ExplanationNextResponse",
            fields={
                "request_id": serializers.CharField(),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": serializers.DictField(),
            },
        ),
    )
    def post(self, request, wrong_question_id):
        request_serializer = ExplanationNextSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data
        wrong_question = get_owned_wrong_question(
            wrong_question_id=wrong_question_id,
            tenant_id=request.user.tenant_id,
            student_id=request.user.identifier,
        )
        if wrong_question.status not in {
            WrongQuestion.Status.CONFIRMED,
            WrongQuestion.Status.LEARNING,
        }:
            raise ConflictError(
                f"explanation cannot start from status {wrong_question.status}"
            )
        question_html = wrong_question.question.get("stem_html")
        if not question_html:
            raise AIResultNeedsReviewError("confirmed question has no usable stem")
        knowledge_point_ids = [
            item.knowledge_point_id
            for item in wrong_question.confirmed_knowledge_points.all()
        ]
        if not knowledge_point_ids:
            raise AIResultNeedsReviewError(
                "confirmed question has no confirmed knowledge points"
            )

        response = get_p1_client().guided_next(
            student_id=wrong_question.student_id,
            wrong_question_id=wrong_question.wrong_question_id,
            question_html=question_html,
            knowledge_point_ids=knowledge_point_ids,
            current_step_index=payload["current_step_index"],
            student_input=payload["student_input"],
            mode=payload["mode"],
            request_id=getattr(request, "request_id", None),
            tenant_id=wrong_question.tenant_id,
        )
        if not isinstance(response, dict):
            raise AIServiceUnavailableError("guided explanation response is invalid")
        response["can_show_full_answer"] = False

        with transaction.atomic():
            try:
                current_wrong_question = WrongQuestion.objects.select_for_update().get(
                    pk=wrong_question.pk,
                    tenant_id=request.user.tenant_id,
                    student_id=request.user.identifier,
                )
            except WrongQuestion.DoesNotExist as exc:
                raise NotFound("wrong question not found") from exc
            ExplanationInteraction.objects.create(
                interaction_id=generate_interaction_id(),
                tenant_id=current_wrong_question.tenant_id,
                student_id=current_wrong_question.student_id,
                wrong_question=current_wrong_question,
                current_step_index=payload["current_step_index"],
                student_input=payload["student_input"],
                mode=payload["mode"],
                response=response,
                request_id=getattr(request, "request_id", "") or "",
            )
            if current_wrong_question.status == WrongQuestion.Status.CONFIRMED:
                current_wrong_question.status = WrongQuestion.Status.LEARNING
                current_wrong_question.save(update_fields=["status", "updated_at"])

        return api_response(request, data=response)


class PracticeRecommendationView(StudentAPIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("student_id", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="PracticeRecommendationResponse",
            fields={
                "request_id": serializers.CharField(),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="PracticeRecommendationData",
                    fields={"items": serializers.ListField(child=serializers.DictField())},
                ),
            },
        ),
    )
    def get(self, request):
        query_serializer = PracticeRecommendationQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data
        self.validate_student_id(request, filters["student_id"])
        items = recommend_questions(
            tenant_id=request.user.tenant_id,
            student_id=request.user.identifier,
            limit=filters["limit"],
        )
        return api_response(request, data={"items": items})


class PracticeAnswerView(StudentAPIView):
    @extend_schema(
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                OpenApiTypes.STR,
                OpenApiParameter.HEADER,
                required=False,
                description="重复提交时返回原答题记录，不重复更新掌握度。",
            )
        ],
        request=PracticeAnswerRequestSerializer,
        responses=inline_serializer(
            name="PracticeAnswerResponse",
            fields={
                "request_id": serializers.CharField(),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="PracticeAnswerData",
                    fields={
                        "answer_record_id": serializers.CharField(),
                        "updated_mastery": serializers.ListField(
                            child=serializers.DictField()
                        ),
                    },
                ),
            },
        ),
    )
    def post(self, request):
        request_serializer = PracticeAnswerRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data
        self.validate_student_id(request, payload["student_id"])
        try:
            question = QuestionBankItem.objects.prefetch_related(
                "knowledge_points"
            ).get(
                bank_question_id=payload["bank_question_id"],
                audit_status=QuestionBankItem.AuditStatus.APPROVED,
            )
        except QuestionBankItem.DoesNotExist as exc:
            raise NotFound("approved question not found") from exc

        answer, updated_mastery, _ = record_practice_answer(
            tenant_id=request.user.tenant_id,
            student_id=request.user.identifier,
            question=question,
            answer_text=payload["answer_text"],
            is_correct=payload["is_correct"],
            used_seconds=payload["used_seconds"],
            idempotency_key=self.get_idempotency_key(request),
        )
        return api_response(
            request,
            data={
                "answer_record_id": answer.answer_record_id,
                "updated_mastery": updated_mastery,
            },
        )
