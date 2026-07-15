from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import GeneratedQuestion, KnowledgePoint, PracticePack, QuestionBankItem


class KnowledgePointQuerySerializer(serializers.Serializer):
    subject = serializers.CharField(required=False, allow_blank=False, max_length=32)
    stage = serializers.CharField(required=False, allow_blank=False, max_length=64)
    version = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    enabled = serializers.BooleanField(required=False)


class KnowledgePointSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgePoint
        fields = [
            "knowledge_point_id",
            "code",
            "name",
            "parent_id",
            "subject",
            "stage",
            "grade_range",
            "path",
            "version",
            "enabled",
        ]


class QuestionImportItemSerializer(serializers.Serializer):
    bank_question_id = serializers.CharField(required=False, allow_blank=False, max_length=64)
    content_html = serializers.CharField(allow_blank=False)
    answer_html = serializers.CharField(allow_blank=False)
    analysis_html = serializers.CharField(allow_blank=False)
    knowledge_point_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=64),
        allow_empty=False,
    )
    question_type = serializers.CharField(allow_blank=False, max_length=64)
    difficulty = serializers.FloatField(min_value=0.0, max_value=1.0)
    images = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    audit_status = serializers.ChoiceField(
        choices=QuestionBankItem.AuditStatus.choices,
        required=False,
        default=QuestionBankItem.AuditStatus.APPROVED,
    )


class QuestionImportRequestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=QuestionBankItem.Source.choices)
    knowledge_point_version = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    items = QuestionImportItemSerializer(many=True, allow_empty=False)

    def validate_source(self, value):
        if value == QuestionBankItem.Source.AI_GENERATED:
            raise serializers.ValidationError(
                "AI-generated questions must use the generated-questions review flow."
            )
        return value


class QuestionSearchRequestSerializer(serializers.Serializer):
    knowledge_point_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=64),
        required=False,
        allow_empty=False,
    )
    knowledge_point_version = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    question_type = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=64,
    )
    difficulty_range = serializers.ListField(
        child=serializers.FloatField(min_value=0.0, max_value=1.0),
        required=False,
        allow_empty=False,
    )
    source_priority = serializers.ListField(
        child=serializers.ChoiceField(choices=QuestionBankItem.Source.choices),
        required=False,
        allow_empty=False,
    )
    similar_to = serializers.DictField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=10)

    def validate_difficulty_range(self, value):
        if len(value) != 2:
            raise serializers.ValidationError("difficulty_range must contain exactly two values.")
        if value[0] > value[1]:
            raise serializers.ValidationError("difficulty_range lower bound cannot exceed upper bound.")
        return value


class GeneratedQuestionImportItemSerializer(serializers.Serializer):
    generated_question_id = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=64,
    )
    content_html = serializers.CharField(allow_blank=False)
    answer_html = serializers.CharField(allow_blank=False)
    analysis_html = serializers.CharField(allow_blank=False)
    knowledge_point_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=64),
        allow_empty=False,
    )
    question_type = serializers.CharField(allow_blank=False, max_length=64)
    difficulty = serializers.FloatField(min_value=0.0, max_value=1.0)
    images = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    validation = serializers.DictField(required=False, default=dict)
    raw_response = serializers.DictField(required=False, default=dict)


class GeneratedQuestionImportRequestSerializer(serializers.Serializer):
    source_question_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=64,
    )
    knowledge_point_version = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    model_name = serializers.CharField(required=False, allow_blank=False, max_length=120)
    prompt_version = serializers.CharField(required=False, allow_blank=False, max_length=64)
    raw_request = serializers.DictField(required=False, default=dict)
    items = GeneratedQuestionImportItemSerializer(many=True, allow_empty=False)


class GeneratedQuestionListQuerySerializer(serializers.Serializer):
    audit_status = serializers.ChoiceField(
        choices=GeneratedQuestion.AuditStatus.choices,
        required=False,
    )
    knowledge_point_version = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    knowledge_point_id = serializers.CharField(required=False, allow_blank=False, max_length=64)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=50)


class GeneratedQuestionReviewRequestSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[
            GeneratedQuestion.AuditStatus.APPROVED,
            GeneratedQuestion.AuditStatus.REJECTED,
        ],
    )
    reviewer_id = serializers.CharField(allow_blank=False, max_length=64)
    review_comment = serializers.CharField(required=False, allow_blank=True, default="")
    publish_to_bank = serializers.BooleanField(required=False, default=True)


class GeneratedQuestionSerializer(serializers.ModelSerializer):
    knowledge_point_ids = serializers.SerializerMethodField()
    bank_question_id = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedQuestion
        fields = [
            "generated_question_id",
            "source_question_id",
            "content_html",
            "answer_html",
            "analysis_html",
            "knowledge_point_ids",
            "knowledge_point_version",
            "question_type",
            "difficulty",
            "images",
            "validation",
            "audit_status",
            "reviewer_id",
            "review_comment",
            "reviewed_at",
            "model_name",
            "prompt_version",
            "bank_question_id",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_knowledge_point_ids(self, obj):
        return [
            knowledge_point.knowledge_point_id
            for knowledge_point in obj.knowledge_points.all()
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_bank_question_id(self, obj):
        if obj.bank_question_id is None:
            return None
        return obj.bank_question.bank_question_id


class PracticePackCreateRequestSerializer(serializers.Serializer):
    title = serializers.CharField(allow_blank=False, max_length=120)
    target = serializers.ChoiceField(choices=PracticePack.Target.choices)
    target_ref_id = serializers.CharField(allow_blank=False, max_length=64)
    knowledge_point_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=64),
        allow_empty=False,
    )
    knowledge_point_version = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    question_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=64),
        allow_empty=False,
    )
    created_by = serializers.CharField(allow_blank=False, max_length=64)
