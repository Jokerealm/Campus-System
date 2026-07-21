from django.db import transaction
from django.db.models import Case, IntegerField, When
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.views import APIView

from core.authentication import MockHeaderAuthentication
from core.exceptions import ConflictError
from core.permissions import IsTeacherOrService
from core.responses import api_response

from .models import GeneratedQuestion, KnowledgePoint, PracticePack, QuestionBankItem
from .serializers import (
    GeneratedQuestionImportRequestSerializer,
    GeneratedQuestionListQuerySerializer,
    GeneratedQuestionReviewRequestSerializer,
    GeneratedQuestionSerializer,
    KnowledgePointQuerySerializer,
    KnowledgePointSerializer,
    PracticePackCreateRequestSerializer,
    QuestionImportRequestSerializer,
    QuestionSearchRequestSerializer,
)
from .services import (
    generate_bank_question_id,
    generate_generated_question_id,
    generate_practice_pack_id,
    get_approved_questions_by_public_ids,
    get_knowledge_points_by_public_ids,
    serialize_question_bank_item,
)


class ResourceAPIView(APIView):
    authentication_classes = [MockHeaderAuthentication]
    permission_classes = [IsTeacherOrService]


class KnowledgePointListView(ResourceAPIView):

    @extend_schema(
        parameters=[
            OpenApiParameter("subject", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("stage", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("version", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("enabled", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="KnowledgePointListResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="KnowledgePointListData",
                    fields={
                        "version": serializers.CharField(),
                        "items": KnowledgePointSerializer(many=True),
                    },
                ),
            },
        ),
        examples=[
            OpenApiExample(
                "Success",
                value={
                    "request_id": "req_001",
                    "code": "OK",
                    "message": "success",
                    "data": {
                        "version": "2026.1",
                        "items": [
                            {
                                "knowledge_point_id": "kp_math_8_function_linear",
                                "code": "MATH.8.FUNC.001",
                                "name": "一次函数图像与性质",
                                "parent_id": "kp_math_8_function",
                                "subject": "math",
                                "stage": "junior_middle_school",
                                "grade_range": ["8"],
                                "path": ["数与代数", "函数", "一次函数图像与性质"],
                                "version": "2026.1",
                                "enabled": True,
                            }
                        ],
                    },
                },
            )
        ],
    )
    def get(self, request):
        query_serializer = KnowledgePointQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        version = filters.get("version", KnowledgePoint.DEFAULT_VERSION)
        queryset = KnowledgePoint.objects.filter(version=version)
        if "subject" in filters:
            queryset = queryset.filter(subject=filters["subject"])
        if "stage" in filters:
            queryset = queryset.filter(stage=filters["stage"])
        if "enabled" in request.query_params:
            queryset = queryset.filter(enabled=filters["enabled"])

        items = KnowledgePointSerializer(queryset, many=True).data
        return api_response(request, data={"version": version, "items": items})


class QuestionImportView(ResourceAPIView):

    @extend_schema(
        request=QuestionImportRequestSerializer,
        responses=inline_serializer(
            name="QuestionImportResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="QuestionImportData",
                    fields={
                        "created_count": serializers.IntegerField(),
                        "updated_count": serializers.IntegerField(),
                        "failed_count": serializers.IntegerField(),
                        "items": serializers.ListField(child=serializers.DictField()),
                    },
                ),
            },
        ),
    )
    def post(self, request):
        request_serializer = QuestionImportRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data

        source = payload["source"]
        knowledge_point_version = payload["knowledge_point_version"]
        import_items = payload["items"]
        knowledge_point_map = self._get_validated_knowledge_points(
            import_items,
            knowledge_point_version,
        )

        response_items = []
        created_count = 0
        updated_count = 0
        with transaction.atomic():
            for item in import_items:
                bank_question_id = item.get("bank_question_id") or generate_bank_question_id()
                question_values = {
                    "source": source,
                    "content_html": item["content_html"],
                    "answer_html": item["answer_html"],
                    "analysis_html": item["analysis_html"],
                    "question_type": item["question_type"],
                    "difficulty": item["difficulty"],
                    "images": item.get("images", []),
                    "audit_status": item["audit_status"],
                    "knowledge_point_version": knowledge_point_version,
                }
                question, created = (
                    QuestionBankItem.objects.select_for_update().get_or_create(
                        bank_question_id=bank_question_id,
                        defaults=question_values,
                    )
                )
                if not created:
                    if question.source == QuestionBankItem.Source.AI_GENERATED:
                        raise ConflictError(
                            "AI-generated bank questions cannot be changed by the "
                            "general import endpoint"
                        )
                    if question.source != source:
                        raise ConflictError(
                            "an imported question cannot change its source"
                        )
                    for field_name, value in question_values.items():
                        setattr(question, field_name, value)
                    question.save(update_fields=[*question_values, "updated_at"])
                question.knowledge_points.set(
                    [
                        knowledge_point_map[knowledge_point_id]
                        for knowledge_point_id in item["knowledge_point_ids"]
                    ]
                )
                if created:
                    created_count += 1
                    status = "created"
                else:
                    updated_count += 1
                    status = "updated"
                response_items.append({"bank_question_id": bank_question_id, "status": status})

        return api_response(
            request,
            data={
                "created_count": created_count,
                "updated_count": updated_count,
                "failed_count": 0,
                "items": response_items,
            },
        )

    def _get_validated_knowledge_points(self, items, version):
        knowledge_point_ids = []
        for item in items:
            knowledge_point_ids.extend(item["knowledge_point_ids"])

        knowledge_point_map, missing_ids = get_knowledge_points_by_public_ids(
            knowledge_point_ids,
            version,
        )
        if missing_ids:
            raise ValidationError(
                {
                    "knowledge_point_ids": [
                        f"Unknown knowledge point ids for version {version}: {', '.join(missing_ids)}"
                    ]
                }
            )
        return knowledge_point_map


class QuestionSearchView(ResourceAPIView):

    @extend_schema(
        request=QuestionSearchRequestSerializer,
        responses=inline_serializer(
            name="QuestionSearchResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="QuestionSearchData",
                    fields={
                        "items": serializers.ListField(child=serializers.DictField()),
                        "need_ai_generation": serializers.BooleanField(),
                    },
                ),
            },
        ),
    )
    def post(self, request):
        request_serializer = QuestionSearchRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        filters = request_serializer.validated_data

        knowledge_point_ids = filters.get("knowledge_point_ids", [])
        knowledge_point_version = filters["knowledge_point_version"]
        if knowledge_point_ids:
            _, missing_ids = get_knowledge_points_by_public_ids(
                knowledge_point_ids,
                knowledge_point_version,
            )
            if missing_ids:
                raise ValidationError(
                    {
                        "knowledge_point_ids": [
                            f"Unknown knowledge point ids for version {knowledge_point_version}: "
                            f"{', '.join(missing_ids)}"
                        ]
                    }
                )

        queryset = QuestionBankItem.objects.prefetch_related("knowledge_points").filter(
            audit_status=QuestionBankItem.AuditStatus.APPROVED,
            knowledge_point_version=knowledge_point_version,
        )
        if knowledge_point_ids:
            queryset = queryset.filter(
                knowledge_points__knowledge_point_id__in=knowledge_point_ids,
                knowledge_points__version=knowledge_point_version,
            ).distinct()
        if filters.get("question_type"):
            queryset = queryset.filter(question_type=filters["question_type"])
        if "difficulty_range" in filters:
            lower_bound, upper_bound = filters["difficulty_range"]
            queryset = queryset.filter(
                difficulty__gte=lower_bound,
                difficulty__lte=upper_bound,
            )

        source_priority = filters.get("source_priority")
        if source_priority:
            source_order = Case(
                *[
                    When(source=source, then=order)
                    for order, source in enumerate(source_priority)
                ],
                default=len(source_priority),
                output_field=IntegerField(),
            )
            queryset = queryset.order_by(
                source_order,
                "difficulty",
                "bank_question_id",
            )
        else:
            queryset = queryset.order_by("difficulty", "bank_question_id")

        limit = filters["limit"]
        questions = list(queryset[:limit])
        requested_knowledge_point_ids = set(knowledge_point_ids)
        items = [
            serialize_question_bank_item(
                question,
                match_score=self._calculate_match_score(
                    question,
                    requested_knowledge_point_ids,
                ),
            )
            for question in questions
        ]
        return api_response(
            request,
            data={
                "items": items,
                "need_ai_generation": len(items) < limit,
            },
        )

    def _calculate_match_score(self, question, requested_knowledge_point_ids):
        if not requested_knowledge_point_ids:
            return 1.0
        question_knowledge_point_ids = {
            knowledge_point.knowledge_point_id
            for knowledge_point in question.knowledge_points.all()
        }
        overlap_count = len(question_knowledge_point_ids & requested_knowledge_point_ids)
        return round(overlap_count / len(requested_knowledge_point_ids), 2)


class GeneratedQuestionCollectionView(ResourceAPIView):

    @extend_schema(
        operation_id="resource_v1_generated_questions_list",
        parameters=[
            OpenApiParameter("audit_status", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("knowledge_point_version", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("knowledge_point_id", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="GeneratedQuestionListResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="GeneratedQuestionListData",
                    fields={
                        "items": GeneratedQuestionSerializer(many=True),
                    },
                ),
            },
        ),
    )
    def get(self, request):
        query_serializer = GeneratedQuestionListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        queryset = GeneratedQuestion.objects.select_related("bank_question").prefetch_related(
            "knowledge_points"
        ).filter(knowledge_point_version=filters["knowledge_point_version"])
        if "audit_status" in filters:
            queryset = queryset.filter(audit_status=filters["audit_status"])
        if "knowledge_point_id" in filters:
            queryset = queryset.filter(
                knowledge_points__knowledge_point_id=filters["knowledge_point_id"],
                knowledge_points__version=filters["knowledge_point_version"],
            ).distinct()

        items = GeneratedQuestionSerializer(queryset[: filters["limit"]], many=True).data
        return api_response(request, data={"items": items})

    @extend_schema(
        operation_id="resource_v1_generated_questions_create",
        request=GeneratedQuestionImportRequestSerializer,
        responses=inline_serializer(
            name="GeneratedQuestionImportResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="GeneratedQuestionImportData",
                    fields={
                        "saved_count": serializers.IntegerField(),
                        "created_count": serializers.IntegerField(),
                        "updated_count": serializers.IntegerField(),
                        "audit_status": serializers.CharField(),
                        "items": serializers.ListField(child=serializers.DictField()),
                    },
                ),
            },
        ),
    )
    def post(self, request):
        request_serializer = GeneratedQuestionImportRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data

        knowledge_point_version = payload["knowledge_point_version"]
        import_items = payload["items"]
        knowledge_point_map = self._get_validated_knowledge_points(
            import_items,
            knowledge_point_version,
        )

        response_items = []
        created_count = 0
        updated_count = 0
        with transaction.atomic():
            for item in import_items:
                generated_question_id = (
                    item.get("generated_question_id") or generate_generated_question_id()
                )
                defaults = {
                    "source_question_id": payload.get("source_question_id"),
                    "content_html": item["content_html"],
                    "answer_html": item["answer_html"],
                    "analysis_html": item["analysis_html"],
                    "question_type": item["question_type"],
                    "difficulty": item["difficulty"],
                    "images": item.get("images", []),
                    "validation": item.get("validation", {}),
                    "audit_status": GeneratedQuestion.AuditStatus.PENDING_REVIEW,
                    "knowledge_point_version": knowledge_point_version,
                    "reviewer_id": None,
                    "review_comment": "",
                    "reviewed_at": None,
                    "model_name": payload.get("model_name", ""),
                    "prompt_version": payload.get("prompt_version", ""),
                    "raw_request": payload.get("raw_request", {}),
                    "raw_response": item.get("raw_response", {}),
                    "bank_question": None,
                }
                generated_question, created = self._create_or_update_generated_question(
                    generated_question_id,
                    defaults,
                )
                knowledge_point_ids = list(dict.fromkeys(item["knowledge_point_ids"]))
                generated_question.knowledge_points.set(
                    [
                        knowledge_point_map[knowledge_point_id]
                        for knowledge_point_id in knowledge_point_ids
                    ]
                )
                if created:
                    created_count += 1
                    status = "created"
                else:
                    updated_count += 1
                    status = "updated"
                response_items.append(
                    {
                        "generated_question_id": generated_question_id,
                        "status": status,
                        "audit_status": generated_question.audit_status,
                    }
                )

        return api_response(
            request,
            data={
                "saved_count": created_count + updated_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "audit_status": GeneratedQuestion.AuditStatus.PENDING_REVIEW,
                "items": response_items,
            },
        )

    def _get_validated_knowledge_points(self, items, version):
        knowledge_point_ids = []
        for item in items:
            knowledge_point_ids.extend(item["knowledge_point_ids"])

        knowledge_point_map, missing_ids = get_knowledge_points_by_public_ids(
            knowledge_point_ids,
            version,
        )
        if missing_ids:
            raise ValidationError(
                {
                    "knowledge_point_ids": [
                        f"Unknown knowledge point ids for version {version}: {', '.join(missing_ids)}"
                    ]
                }
            )
        return knowledge_point_map

    def _create_or_update_generated_question(self, generated_question_id, defaults):
        generated_question, created = (
            GeneratedQuestion.objects.select_for_update().get_or_create(
                generated_question_id=generated_question_id,
                defaults=defaults,
            )
        )

        if created:
            return generated_question, created

        if generated_question.audit_status != GeneratedQuestion.AuditStatus.PENDING_REVIEW:
            raise ConflictError(
                f"Generated question has already been reviewed: {generated_question_id}"
            )

        for field_name, value in defaults.items():
            setattr(generated_question, field_name, value)
        generated_question.save(update_fields=[*defaults.keys(), "updated_at"])
        return generated_question, created


class GeneratedQuestionDetailView(ResourceAPIView):

    @extend_schema(
        operation_id="resource_v1_generated_questions_retrieve",
        responses=inline_serializer(
            name="GeneratedQuestionDetailResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": GeneratedQuestionSerializer(),
            },
        ),
    )
    def get(self, request, generated_question_id):
        generated_question = self._get_generated_question(generated_question_id)
        return api_response(
            request,
            data=GeneratedQuestionSerializer(generated_question).data,
        )

    def _get_generated_question(self, generated_question_id):
        try:
            return (
                GeneratedQuestion.objects.select_related("bank_question")
                .prefetch_related("knowledge_points")
                .get(generated_question_id=generated_question_id)
            )
        except GeneratedQuestion.DoesNotExist as exc:
            raise NotFound("generated question not found") from exc


class GeneratedQuestionReviewView(ResourceAPIView):

    @extend_schema(
        operation_id="resource_v1_generated_questions_review",
        request=GeneratedQuestionReviewRequestSerializer,
        responses=inline_serializer(
            name="GeneratedQuestionReviewResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="GeneratedQuestionReviewData",
                    fields={
                        "generated_question_id": serializers.CharField(),
                        "audit_status": serializers.CharField(),
                        "bank_question_id": serializers.CharField(allow_null=True),
                    },
                ),
            },
        ),
    )
    def put(self, request, generated_question_id):
        request_serializer = GeneratedQuestionReviewRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data
        self._validate_teacher_field(request, payload, "reviewer_id")

        with transaction.atomic():
            generated_question = self._get_locked_generated_question(generated_question_id)
            if generated_question.audit_status != GeneratedQuestion.AuditStatus.PENDING_REVIEW:
                raise ConflictError("generated question has already been reviewed")

            bank_question = None
            should_publish = (
                payload["decision"] == GeneratedQuestion.AuditStatus.APPROVED
                and payload["publish_to_bank"]
            )
            if should_publish:
                knowledge_points = list(generated_question.knowledge_points.all())
                if not knowledge_points:
                    raise ValidationError(
                        {"knowledge_point_ids": ["generated question has no knowledge points"]}
                    )
                bank_question = QuestionBankItem.objects.create(
                    bank_question_id=generate_bank_question_id(),
                    source=QuestionBankItem.Source.AI_GENERATED,
                    content_html=generated_question.content_html,
                    answer_html=generated_question.answer_html,
                    analysis_html=generated_question.analysis_html,
                    question_type=generated_question.question_type,
                    difficulty=generated_question.difficulty,
                    images=generated_question.images,
                    audit_status=QuestionBankItem.AuditStatus.APPROVED,
                    knowledge_point_version=generated_question.knowledge_point_version,
                )
                bank_question.knowledge_points.set(knowledge_points)

            generated_question.audit_status = payload["decision"]
            generated_question.reviewer_id = payload["reviewer_id"]
            generated_question.review_comment = payload["review_comment"]
            generated_question.reviewed_at = timezone.now()
            generated_question.bank_question = bank_question
            generated_question.save(
                update_fields=[
                    "audit_status",
                    "reviewer_id",
                    "review_comment",
                    "reviewed_at",
                    "bank_question",
                    "updated_at",
                ]
            )

        return api_response(
            request,
            data={
                "generated_question_id": generated_question.generated_question_id,
                "audit_status": generated_question.audit_status,
                "bank_question_id": (
                    bank_question.bank_question_id if bank_question is not None else None
                ),
            },
        )

    def _get_locked_generated_question(self, generated_question_id):
        try:
            return (
                GeneratedQuestion.objects.select_for_update()
                .prefetch_related("knowledge_points")
                .get(generated_question_id=generated_question_id)
            )
        except GeneratedQuestion.DoesNotExist as exc:
            raise NotFound("generated question not found") from exc

    @staticmethod
    def _validate_teacher_field(request, payload, field_name):
        if (
            request.user.role == "teacher"
            and payload[field_name] != request.user.identifier
        ):
            raise ValidationError(
                {field_name: [f"must match X-Teacher-Id ({request.user.identifier})"]}
            )


class PracticePackCreateView(ResourceAPIView):

    @extend_schema(
        request=PracticePackCreateRequestSerializer,
        responses=inline_serializer(
            name="PracticePackCreateResponse",
            fields={
                "request_id": serializers.CharField(allow_null=True),
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "data": inline_serializer(
                    name="PracticePackCreateData",
                    fields={
                        "practice_pack_id": serializers.CharField(),
                        "status": serializers.CharField(),
                    },
                ),
            },
        ),
        examples=[
            OpenApiExample(
                "Success",
                value={
                    "request_id": "req_pack_001",
                    "code": "OK",
                    "message": "success",
                    "data": {
                        "practice_pack_id": "pack_001",
                        "status": "draft",
                    },
                },
            )
        ],
    )
    def post(self, request):
        request_serializer = PracticePackCreateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = request_serializer.validated_data
        self._validate_teacher_field(request, payload, "created_by")

        knowledge_point_version = payload["knowledge_point_version"]
        knowledge_point_map = self._get_validated_knowledge_points(
            payload["knowledge_point_ids"],
            knowledge_point_version,
        )
        question_map = self._get_validated_questions(
            payload["question_ids"],
            knowledge_point_version,
        )

        knowledge_point_ids = list(dict.fromkeys(payload["knowledge_point_ids"]))
        question_ids = list(dict.fromkeys(payload["question_ids"]))
        with transaction.atomic():
            practice_pack = PracticePack.objects.create(
                practice_pack_id=generate_practice_pack_id(),
                title=payload["title"],
                target=payload["target"],
                target_ref_id=payload["target_ref_id"],
                knowledge_point_version=knowledge_point_version,
                created_by=payload["created_by"],
                status=PracticePack.Status.DRAFT,
            )
            practice_pack.knowledge_points.set(
                [
                    knowledge_point_map[knowledge_point_id]
                    for knowledge_point_id in knowledge_point_ids
                ]
            )
            practice_pack.questions.set(
                [question_map[question_id] for question_id in question_ids]
            )

        return api_response(
            request,
            data={
                "practice_pack_id": practice_pack.practice_pack_id,
                "status": practice_pack.status,
            },
        )

    def _get_validated_knowledge_points(self, knowledge_point_ids, version):
        knowledge_point_map, missing_ids = get_knowledge_points_by_public_ids(
            knowledge_point_ids,
            version,
        )
        if missing_ids:
            raise ValidationError(
                {
                    "knowledge_point_ids": [
                        f"Unknown knowledge point ids for version {version}: {', '.join(missing_ids)}"
                    ]
                }
            )
        return knowledge_point_map

    def _get_validated_questions(self, question_ids, version):
        question_map, missing_ids = get_approved_questions_by_public_ids(
            question_ids,
            version,
        )
        if missing_ids:
            raise ValidationError(
                {
                    "question_ids": [
                        "Unknown, unapproved, or version-mismatched question ids for "
                        f"version {version}: {', '.join(missing_ids)}"
                    ]
                }
            )
        return question_map

    @staticmethod
    def _validate_teacher_field(request, payload, field_name):
        if (
            request.user.role == "teacher"
            and payload[field_name] != request.user.identifier
        ):
            raise ValidationError(
                {field_name: [f"must match X-Teacher-Id ({request.user.identifier})"]}
            )
