import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models

from resources.models import KnowledgePoint, QuestionBankItem


DEFAULT_TENANT_ID = "default"


def wrong_question_upload_to(instance, filename):
    """Store uploads under opaque names and never trust the client-side path."""

    suffix = Path(filename).suffix.lower()[:16]
    return f"students/wrong_questions/{uuid.uuid4().hex}{suffix}"


class WrongQuestion(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        RECOGNIZING = "recognizing", "Recognizing"
        RECOGNITION_FAILED = "recognition_failed", "Recognition failed"
        RECOGNIZED = "recognized", "Recognized"
        CONFIRMED = "confirmed", "Confirmed"
        LEARNING = "learning", "Learning"
        MASTERED = "mastered", "Mastered"

    wrong_question_id = models.CharField(max_length=64, unique=True)
    tenant_id = models.CharField(max_length=64, default=DEFAULT_TENANT_ID)
    student_id = models.CharField(max_length=64)
    subject = models.CharField(max_length=32)
    grade = models.CharField(max_length=32)
    file = models.FileField(upload_to=wrong_question_upload_to, max_length=255)
    recognition_job_id = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        unique=True,
    )
    recognition_error = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.UPLOADED,
    )
    question = models.JSONField(default=dict)
    knowledge_candidates = models.JSONField(default=list)
    knowledge_point_version = models.CharField(
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    confirmed_knowledge_points = models.ManyToManyField(
        KnowledgePoint,
        related_name="wrong_questions",
        blank=True,
    )
    idempotency_key = models.CharField(max_length=128, blank=True, default="")
    idempotency_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "wrong_question_id"]
        indexes = [
            models.Index(fields=["tenant_id", "student_id", "status", "created_at"]),
            models.Index(fields=["knowledge_point_version", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "uploaded",
                        "recognizing",
                        "recognition_failed",
                        "recognized",
                        "confirmed",
                        "learning",
                        "mastered",
                    )
                ),
                name="students_wq_status_valid",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "student_id", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="students_wq_idempotency_unique",
            ),
        ]

    def __str__(self):
        return f"{self.wrong_question_id} {self.student_id} {self.status}"


class PracticeAnswer(models.Model):
    answer_record_id = models.CharField(max_length=64, unique=True)
    tenant_id = models.CharField(max_length=64, default=DEFAULT_TENANT_ID)
    student_id = models.CharField(max_length=64)
    question = models.ForeignKey(
        QuestionBankItem,
        related_name="practice_answers",
        on_delete=models.PROTECT,
    )
    knowledge_point_version = models.CharField(
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    answer_text = models.TextField(blank=True)
    is_correct = models.BooleanField()
    used_seconds = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=128, blank=True, default="")
    idempotency_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    mastery_snapshot = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "answer_record_id"]
        indexes = [
            models.Index(fields=["tenant_id", "student_id", "created_at"]),
            models.Index(fields=["question", "created_at"]),
            models.Index(fields=["knowledge_point_version", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "student_id", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="students_pa_idempotency_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.question_id
            and self.knowledge_point_version
            != self.question.knowledge_point_version
        ):
            raise ValidationError(
                {
                    "knowledge_point_version": (
                        "The answer version must match its question bank item."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.question_id:
            self.knowledge_point_version = self.question.knowledge_point_version
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.answer_record_id} {self.student_id}"


class StudentMastery(models.Model):
    tenant_id = models.CharField(max_length=64, default=DEFAULT_TENANT_ID)
    student_id = models.CharField(max_length=64)
    knowledge_point = models.ForeignKey(
        KnowledgePoint,
        related_name="student_masteries",
        on_delete=models.PROTECT,
    )
    knowledge_point_version = models.CharField(
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    mastery_rate = models.FloatField(default=0.5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "student_id", "knowledge_point_id"]
        indexes = [
            models.Index(fields=["tenant_id", "student_id", "updated_at"]),
            models.Index(fields=["knowledge_point_version", "mastery_rate"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "tenant_id",
                    "student_id",
                    "knowledge_point",
                    "knowledge_point_version",
                ],
                name="students_mastery_student_kp_version_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(mastery_rate__gte=0.0)
                    & models.Q(mastery_rate__lte=1.0)
                ),
                name="students_mastery_rate_range",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.knowledge_point_id
            and self.knowledge_point_version != self.knowledge_point.version
        ):
            raise ValidationError(
                {
                    "knowledge_point_version": (
                        "The mastery version must match its knowledge point."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.knowledge_point_id:
            self.knowledge_point_version = self.knowledge_point.version
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.tenant_id}/{self.student_id} "
            f"{self.knowledge_point.knowledge_point_id}: {self.mastery_rate:.3f}"
        )


class ExplanationInteraction(models.Model):
    class Mode(models.TextChoices):
        HINT = "hint", "Hint"
        CHECK = "check", "Check"
        EXPLAIN = "explain", "Explain"
        SUMMARY = "summary", "Summary"

    interaction_id = models.CharField(max_length=64, unique=True)
    tenant_id = models.CharField(max_length=64, default=DEFAULT_TENANT_ID)
    student_id = models.CharField(max_length=64)
    wrong_question = models.ForeignKey(
        WrongQuestion,
        related_name="explanation_interactions",
        on_delete=models.CASCADE,
    )
    current_step_index = models.PositiveIntegerField(default=0)
    student_input = models.TextField(blank=True)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    response = models.JSONField(default=dict)
    request_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "interaction_id"]
        indexes = [
            models.Index(
                fields=["tenant_id", "student_id", "wrong_question", "created_at"]
            ),
            models.Index(fields=["wrong_question", "current_step_index"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode__in=("hint", "check", "explain", "summary")),
                name="students_explanation_mode_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if self.wrong_question_id and (
            self.tenant_id != self.wrong_question.tenant_id
            or self.student_id != self.wrong_question.student_id
        ):
            raise ValidationError(
                "The interaction owner must match the wrong question owner."
            )

    def __str__(self):
        return f"{self.interaction_id} {self.mode} step={self.current_step_index}"
