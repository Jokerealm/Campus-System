from django.db import models


class KnowledgePoint(models.Model):
    DEFAULT_VERSION = "2026.1"

    knowledge_point_id = models.CharField(max_length=64, db_index=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    parent_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    subject = models.CharField(max_length=32)
    stage = models.CharField(max_length=64)
    grade_range = models.JSONField(default=list)
    path = models.JSONField(default=list)
    version = models.CharField(max_length=32, default=DEFAULT_VERSION)
    enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "code"]
        indexes = [
            models.Index(fields=["subject", "stage", "version", "enabled"]),
            models.Index(fields=["version", "code"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["knowledge_point_id", "version"],
                name="unique_knowledge_point_id_version",
            ),
            models.UniqueConstraint(
                fields=["code", "version"],
                name="unique_knowledge_point_code_version",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class QuestionBankItem(models.Model):
    class Source(models.TextChoices):
        SCHOOL_BANK = "school_bank", "School bank"
        EXAM_HISTORY = "exam_history", "Exam history"
        MIDDLE_EXAM_REAL = "middle_exam_real", "Middle exam real"
        EXTERNAL_IMPORT = "external_import", "External import"
        AI_GENERATED = "ai_generated", "AI generated"

    class AuditStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    bank_question_id = models.CharField(max_length=64, unique=True)
    source = models.CharField(max_length=32, choices=Source.choices)
    content_html = models.TextField()
    answer_html = models.TextField()
    analysis_html = models.TextField()
    question_type = models.CharField(max_length=64)
    difficulty = models.FloatField()
    images = models.JSONField(default=list)
    audit_status = models.CharField(
        max_length=32,
        choices=AuditStatus.choices,
        default=AuditStatus.APPROVED,
    )
    knowledge_point_version = models.CharField(
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    knowledge_points = models.ManyToManyField(
        KnowledgePoint,
        related_name="question_bank_items",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "bank_question_id"]
        indexes = [
            models.Index(fields=["source", "audit_status"]),
            models.Index(fields=["knowledge_point_version", "audit_status"]),
            models.Index(fields=["difficulty"]),
        ]

    def __str__(self):
        return f"{self.bank_question_id} {self.question_type}"


class GeneratedQuestion(models.Model):
    class AuditStatus(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    generated_question_id = models.CharField(max_length=64, unique=True)
    source_question_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
    )
    content_html = models.TextField()
    answer_html = models.TextField()
    analysis_html = models.TextField()
    question_type = models.CharField(max_length=64)
    difficulty = models.FloatField()
    images = models.JSONField(default=list)
    validation = models.JSONField(default=dict)
    audit_status = models.CharField(
        max_length=32,
        choices=AuditStatus.choices,
        default=AuditStatus.PENDING_REVIEW,
    )
    knowledge_point_version = models.CharField(
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    knowledge_points = models.ManyToManyField(
        KnowledgePoint,
        related_name="generated_questions",
        blank=True,
    )
    reviewer_id = models.CharField(max_length=64, blank=True, null=True)
    review_comment = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=64, blank=True)
    raw_request = models.JSONField(default=dict)
    raw_response = models.JSONField(default=dict)
    bank_question = models.OneToOneField(
        QuestionBankItem,
        related_name="generated_question",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "generated_question_id"]
        indexes = [
            models.Index(fields=["audit_status", "created_at"]),
            models.Index(fields=["knowledge_point_version", "audit_status"]),
            models.Index(fields=["source_question_id"]),
        ]

    def __str__(self):
        return f"{self.generated_question_id} {self.audit_status}"


class PracticePack(models.Model):
    class Target(models.TextChoices):
        CLASS = "class", "Class"
        STUDENT = "student", "Student"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    practice_pack_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=120)
    target = models.CharField(max_length=16, choices=Target.choices)
    target_ref_id = models.CharField(max_length=64, db_index=True)
    knowledge_point_version = models.CharField(
        max_length=32,
        default=KnowledgePoint.DEFAULT_VERSION,
    )
    knowledge_points = models.ManyToManyField(
        KnowledgePoint,
        related_name="practice_packs",
        blank=True,
    )
    questions = models.ManyToManyField(
        QuestionBankItem,
        related_name="practice_packs",
        blank=True,
    )
    created_by = models.CharField(max_length=64)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "practice_pack_id"]
        indexes = [
            models.Index(fields=["target", "target_ref_id", "status"]),
            models.Index(fields=["created_by", "status"]),
            models.Index(fields=["knowledge_point_version", "status"]),
        ]

    def __str__(self):
        return f"{self.practice_pack_id} {self.title}"
