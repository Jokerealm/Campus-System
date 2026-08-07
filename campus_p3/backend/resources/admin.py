from django.contrib import admin

from .models import GeneratedQuestion, KnowledgePoint, PracticePack, QuestionBankItem


@admin.register(KnowledgePoint)
class KnowledgePointAdmin(admin.ModelAdmin):
    list_display = [
        "knowledge_point_id",
        "code",
        "name",
        "subject",
        "stage",
        "version",
        "enabled",
    ]
    list_filter = ["subject", "stage", "version", "enabled"]
    search_fields = ["knowledge_point_id", "code", "name"]
    ordering = ["sort_order", "code"]


@admin.register(QuestionBankItem)
class QuestionBankItemAdmin(admin.ModelAdmin):
    list_display = [
        "bank_question_id",
        "source",
        "question_type",
        "difficulty",
        "audit_status",
        "knowledge_point_version",
        "created_at",
    ]
    list_filter = ["source", "question_type", "audit_status", "knowledge_point_version"]
    search_fields = ["bank_question_id", "content_html", "analysis_html"]
    filter_horizontal = ["knowledge_points"]
    ordering = ["-created_at", "bank_question_id"]


@admin.register(GeneratedQuestion)
class GeneratedQuestionAdmin(admin.ModelAdmin):
    list_display = [
        "generated_question_id",
        "source_question_id",
        "question_type",
        "difficulty",
        "audit_status",
        "knowledge_point_version",
        "reviewer_id",
        "created_at",
    ]
    list_filter = ["audit_status", "question_type", "knowledge_point_version"]
    search_fields = ["generated_question_id", "source_question_id", "content_html"]
    filter_horizontal = ["knowledge_points"]
    ordering = ["-created_at", "generated_question_id"]


@admin.register(PracticePack)
class PracticePackAdmin(admin.ModelAdmin):
    list_display = [
        "practice_pack_id",
        "title",
        "target",
        "target_ref_id",
        "status",
        "created_by",
        "created_at",
    ]
    list_filter = ["target", "status", "knowledge_point_version"]
    search_fields = ["practice_pack_id", "title", "target_ref_id", "created_by"]
    filter_horizontal = ["knowledge_points", "questions"]
    ordering = ["-created_at", "practice_pack_id"]
