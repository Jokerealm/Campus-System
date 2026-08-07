from django.contrib import admin

from .models import (
    ExplanationInteraction,
    PracticeAnswer,
    StudentMastery,
    WrongQuestion,
)


@admin.register(WrongQuestion)
class WrongQuestionAdmin(admin.ModelAdmin):
    list_display = [
        "wrong_question_id",
        "tenant_id",
        "student_id",
        "subject",
        "grade",
        "status",
        "knowledge_point_version",
        "created_at",
    ]
    list_filter = ["tenant_id", "subject", "grade", "status", "knowledge_point_version"]
    search_fields = [
        "wrong_question_id",
        "student_id",
        "recognition_job_id",
        "idempotency_key",
    ]
    filter_horizontal = ["confirmed_knowledge_points"]
    ordering = ["-created_at", "wrong_question_id"]


@admin.register(PracticeAnswer)
class PracticeAnswerAdmin(admin.ModelAdmin):
    list_display = [
        "answer_record_id",
        "tenant_id",
        "student_id",
        "question",
        "is_correct",
        "used_seconds",
        "knowledge_point_version",
        "created_at",
    ]
    list_filter = ["tenant_id", "is_correct", "knowledge_point_version"]
    search_fields = [
        "answer_record_id",
        "student_id",
        "question__bank_question_id",
        "idempotency_key",
    ]
    ordering = ["-created_at", "answer_record_id"]


@admin.register(StudentMastery)
class StudentMasteryAdmin(admin.ModelAdmin):
    list_display = [
        "tenant_id",
        "student_id",
        "knowledge_point",
        "knowledge_point_version",
        "mastery_rate",
        "updated_at",
    ]
    list_filter = ["tenant_id", "knowledge_point_version"]
    search_fields = [
        "student_id",
        "knowledge_point__knowledge_point_id",
        "knowledge_point__code",
        "knowledge_point__name",
    ]
    ordering = ["tenant_id", "student_id", "knowledge_point_id"]


@admin.register(ExplanationInteraction)
class ExplanationInteractionAdmin(admin.ModelAdmin):
    list_display = [
        "interaction_id",
        "tenant_id",
        "student_id",
        "wrong_question",
        "current_step_index",
        "mode",
        "created_at",
    ]
    list_filter = ["tenant_id", "mode"]
    search_fields = [
        "interaction_id",
        "student_id",
        "wrong_question__wrong_question_id",
        "request_id",
    ]
    ordering = ["-created_at", "interaction_id"]
