import hashlib
import json
import uuid

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound

from core.exceptions import ConflictError
from resources.models import QuestionBankItem

from .models import PracticeAnswer, StudentMastery, WrongQuestion


MASTERY_INITIAL = 0.5
MASTERY_CORRECT_DELTA = 0.05
MASTERY_INCORRECT_DELTA = -0.08
MASTERY_THRESHOLD = 0.8


def generate_wrong_question_id():
    return _generate_public_id("wq", WrongQuestion, "wrong_question_id")


def generate_answer_record_id():
    return _generate_public_id("ans", PracticeAnswer, "answer_record_id")


def generate_interaction_id():
    return f"interaction_{uuid.uuid4().hex[:16]}"


def _generate_public_id(prefix, model, field_name):
    for _ in range(10):
        value = f"{prefix}_{uuid.uuid4().hex[:16]}"
        if not model.objects.filter(**{field_name: value}).exists():
            return value
    return f"{prefix}_{uuid.uuid4().hex}"


def get_owned_wrong_question(*, wrong_question_id, tenant_id, student_id):
    try:
        return (
            WrongQuestion.objects.prefetch_related("confirmed_knowledge_points")
            .get(
                wrong_question_id=wrong_question_id,
                tenant_id=tenant_id,
                student_id=student_id,
            )
        )
    except WrongQuestion.DoesNotExist as exc:
        raise NotFound("wrong question not found") from exc


def serialize_wrong_question(wrong_question):
    return {
        "wrong_question_id": wrong_question.wrong_question_id,
        "student_id": wrong_question.student_id,
        "subject": wrong_question.subject,
        "grade": wrong_question.grade,
        "recognition_job_id": wrong_question.recognition_job_id,
        "recognition_error": wrong_question.recognition_error,
        "status": wrong_question.status,
        "question": wrong_question.question,
        "knowledge_candidates": wrong_question.knowledge_candidates,
        "knowledge_point_version": wrong_question.knowledge_point_version,
        "confirmed_knowledge_point_ids": [
            knowledge_point.knowledge_point_id
            for knowledge_point in wrong_question.confirmed_knowledge_points.all()
        ],
        "created_at": wrong_question.created_at,
        "updated_at": wrong_question.updated_at,
    }


def recommend_questions(*, tenant_id, student_id, limit):
    wrong_questions = list(
        WrongQuestion.objects.filter(
            tenant_id=tenant_id,
            student_id=student_id,
            status__in=[
                WrongQuestion.Status.CONFIRMED,
                WrongQuestion.Status.LEARNING,
                WrongQuestion.Status.MASTERED,
            ],
        )
        .prefetch_related("confirmed_knowledge_points")
        .order_by("-updated_at")[:20]
    )

    preferred_ids = []
    version = None
    for wrong_question in wrong_questions:
        if version is None:
            version = wrong_question.knowledge_point_version
        if wrong_question.knowledge_point_version != version:
            continue
        for knowledge_point in wrong_question.confirmed_knowledge_points.all():
            if knowledge_point.knowledge_point_id not in preferred_ids:
                preferred_ids.append(knowledge_point.knowledge_point_id)

    mastery_rows = list(
        StudentMastery.objects.filter(
            tenant_id=tenant_id,
            student_id=student_id,
        )
        .select_related("knowledge_point")
        .order_by("mastery_rate", "updated_at")
    )
    if version is None and mastery_rows:
        version = mastery_rows[0].knowledge_point_version
    if version is None:
        version = "2026.1"
    for mastery in mastery_rows:
        public_id = mastery.knowledge_point.knowledge_point_id
        if mastery.knowledge_point_version == version and public_id not in preferred_ids:
            preferred_ids.append(public_id)

    approved_queryset = QuestionBankItem.objects.filter(
        audit_status=QuestionBankItem.AuditStatus.APPROVED,
        knowledge_point_version=version,
    ).prefetch_related("knowledge_points")
    queryset = approved_queryset
    if preferred_ids:
        preferred_queryset = approved_queryset.filter(
            knowledge_points__knowledge_point_id__in=preferred_ids,
            knowledge_points__version=version,
        ).distinct()
        if preferred_queryset.exists():
            queryset = preferred_queryset

    already_answered_ids = set(
        PracticeAnswer.objects.filter(
            tenant_id=tenant_id,
            student_id=student_id,
        ).values_list("question_id", flat=True)
    )
    questions = list(queryset[:200])

    mastery_by_id = {
        row.knowledge_point.knowledge_point_id: row.mastery_rate
        for row in mastery_rows
        if row.knowledge_point_version == version
    }
    source_rank = {
        QuestionBankItem.Source.SCHOOL_BANK: 0,
        QuestionBankItem.Source.EXAM_HISTORY: 1,
        QuestionBankItem.Source.MIDDLE_EXAM_REAL: 2,
        QuestionBankItem.Source.EXTERNAL_IMPORT: 3,
        QuestionBankItem.Source.AI_GENERATED: 4,
    }

    def sort_key(question):
        ids = [item.knowledge_point_id for item in question.knowledge_points.all()]
        preferred_rank = min(
            (preferred_ids.index(item_id) for item_id in ids if item_id in preferred_ids),
            default=len(preferred_ids),
        )
        rates = [mastery_by_id[item_id] for item_id in ids if item_id in mastery_by_id]
        average_mastery = sum(rates) / len(rates) if rates else MASTERY_INITIAL
        target_difficulty = max(0.3, min(0.6, average_mastery - 0.05))
        return (
            question.id in already_answered_ids,
            preferred_rank,
            abs(question.difficulty - target_difficulty),
            source_rank.get(question.source, 99),
            question.bank_question_id,
        )

    questions.sort(key=sort_key)
    items = []
    for question in questions[:limit]:
        knowledge_point_ids = [
            knowledge_point.knowledge_point_id
            for knowledge_point in question.knowledge_points.all()
        ]
        matched_recent = any(item in preferred_ids for item in knowledge_point_ids)
        if matched_recent:
            recommend_reason = (
                "与最近错题或薄弱知识点相同，"
                "并优先选择中等或略低难度。"
            )
        elif preferred_ids:
            recommend_reason = (
                "偏好知识点暂无可用的已审核题目，"
                "回退推荐同版本的已审核题目。"
            )
        else:
            recommend_reason = (
                "当前没有已确认错题，推荐一组中等难度的已审核题目。"
            )
        items.append(
            {
                "bank_question_id": question.bank_question_id,
                "content_html": question.content_html,
                "knowledge_point_ids": knowledge_point_ids,
                "knowledge_point_version": question.knowledge_point_version,
                "question_type": question.question_type,
                "difficulty": question.difficulty,
                "images": question.images,
                "recommend_reason": recommend_reason,
            }
        )
    return items


@transaction.atomic
def record_practice_answer(
    *,
    tenant_id,
    student_id,
    question,
    answer_text,
    is_correct,
    used_seconds,
    idempotency_key="",
):
    idempotency_fingerprint = _answer_fingerprint(
        question=question,
        answer_text=answer_text,
        is_correct=is_correct,
        used_seconds=used_seconds,
    )
    if idempotency_key:
        existing = PracticeAnswer.objects.filter(
            tenant_id=tenant_id,
            student_id=student_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            _validate_answer_replay(existing, idempotency_fingerprint)
            return existing, existing.mastery_snapshot or _current_mastery(existing), False

    try:
        # The inner savepoint lets a concurrent idempotent insert lose its
        # unique-key race without marking the surrounding transaction broken.
        with transaction.atomic():
            answer = PracticeAnswer.objects.create(
                answer_record_id=generate_answer_record_id(),
                tenant_id=tenant_id,
                student_id=student_id,
                question=question,
                answer_text=answer_text,
                is_correct=is_correct,
                used_seconds=used_seconds,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=idempotency_fingerprint,
            )
    except IntegrityError:
        if not idempotency_key:
            raise
        existing = PracticeAnswer.objects.filter(
            tenant_id=tenant_id,
            student_id=student_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing is None:
            raise
        _validate_answer_replay(existing, idempotency_fingerprint)
        return existing, existing.mastery_snapshot or _current_mastery(existing), False

    updated_mastery = []
    delta = MASTERY_CORRECT_DELTA if is_correct else MASTERY_INCORRECT_DELTA
    for knowledge_point in question.knowledge_points.all():
        mastery, _ = StudentMastery.objects.select_for_update().get_or_create(
            tenant_id=tenant_id,
            student_id=student_id,
            knowledge_point=knowledge_point,
            knowledge_point_version=question.knowledge_point_version,
            defaults={"mastery_rate": MASTERY_INITIAL},
        )
        mastery.mastery_rate = round(
            max(0.0, min(1.0, mastery.mastery_rate + delta)),
            4,
        )
        mastery.save(update_fields=["mastery_rate", "updated_at"])
        updated_mastery.append(
            {
                "knowledge_point_id": knowledge_point.knowledge_point_id,
                "mastery_rate": mastery.mastery_rate,
            }
        )

    _update_mastered_wrong_questions(tenant_id=tenant_id, student_id=student_id)
    answer.mastery_snapshot = updated_mastery
    answer.save(update_fields=["mastery_snapshot"])
    return answer, updated_mastery, True


def _answer_fingerprint(*, question, answer_text, is_correct, used_seconds):
    encoded = json.dumps(
        {
            "bank_question_id": question.bank_question_id,
            "answer_text": answer_text,
            "is_correct": is_correct,
            "used_seconds": used_seconds,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_answer_replay(answer, fingerprint):
    if (
        answer.idempotency_fingerprint
        and answer.idempotency_fingerprint != fingerprint
    ):
        raise ConflictError(
            "Idempotency-Key has already been used with a different answer"
        )


def _current_mastery(answer):
    rows = StudentMastery.objects.filter(
        tenant_id=answer.tenant_id,
        student_id=answer.student_id,
        knowledge_point__in=answer.question.knowledge_points.all(),
        knowledge_point_version=answer.knowledge_point_version,
    ).select_related("knowledge_point")
    return [
        {
            "knowledge_point_id": row.knowledge_point.knowledge_point_id,
            "mastery_rate": row.mastery_rate,
        }
        for row in rows
    ]


def _update_mastered_wrong_questions(*, tenant_id, student_id):
    wrong_questions = WrongQuestion.objects.select_for_update().filter(
        tenant_id=tenant_id,
        student_id=student_id,
        status__in=[WrongQuestion.Status.CONFIRMED, WrongQuestion.Status.LEARNING],
    ).prefetch_related("confirmed_knowledge_points")
    rates = {
        (row.knowledge_point_id, row.knowledge_point_version): row.mastery_rate
        for row in StudentMastery.objects.filter(
            tenant_id=tenant_id,
            student_id=student_id,
        )
    }
    for wrong_question in wrong_questions:
        points = list(wrong_question.confirmed_knowledge_points.all())
        if points and all(
            rates.get((point.id, wrong_question.knowledge_point_version), 0.0)
            >= MASTERY_THRESHOLD
            for point in points
        ):
            wrong_question.status = WrongQuestion.Status.MASTERED
            wrong_question.save(update_fields=["status", "updated_at"])
