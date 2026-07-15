import uuid

from .models import GeneratedQuestion, KnowledgePoint, PracticePack, QuestionBankItem


def generate_bank_question_id():
    for _ in range(10):
        bank_question_id = f"bq_{uuid.uuid4().hex[:16]}"
        if not QuestionBankItem.objects.filter(bank_question_id=bank_question_id).exists():
            return bank_question_id
    return f"bq_{uuid.uuid4().hex}"


def generate_practice_pack_id():
    for _ in range(10):
        practice_pack_id = f"pack_{uuid.uuid4().hex[:16]}"
        if not PracticePack.objects.filter(practice_pack_id=practice_pack_id).exists():
            return practice_pack_id
    return f"pack_{uuid.uuid4().hex}"


def generate_generated_question_id():
    for _ in range(10):
        generated_question_id = f"genq_{uuid.uuid4().hex[:16]}"
        if not GeneratedQuestion.objects.filter(
            generated_question_id=generated_question_id
        ).exists():
            return generated_question_id
    return f"genq_{uuid.uuid4().hex}"


def get_knowledge_points_by_public_ids(knowledge_point_ids, version):
    unique_ids = list(dict.fromkeys(knowledge_point_ids))
    knowledge_points = KnowledgePoint.objects.filter(
        knowledge_point_id__in=unique_ids,
        version=version,
    )
    knowledge_point_map = {item.knowledge_point_id: item for item in knowledge_points}
    missing_ids = [item_id for item_id in unique_ids if item_id not in knowledge_point_map]
    return knowledge_point_map, missing_ids


def get_approved_questions_by_public_ids(question_ids, version):
    unique_ids = list(dict.fromkeys(question_ids))
    questions = QuestionBankItem.objects.filter(
        bank_question_id__in=unique_ids,
        knowledge_point_version=version,
        audit_status=QuestionBankItem.AuditStatus.APPROVED,
    )
    question_map = {item.bank_question_id: item for item in questions}
    missing_ids = [item_id for item_id in unique_ids if item_id not in question_map]
    return question_map, missing_ids


def serialize_question_bank_item(question, match_score=None):
    data = {
        "bank_question_id": question.bank_question_id,
        "source": question.source,
        "content_html": question.content_html,
        "answer_html": question.answer_html,
        "analysis_html": question.analysis_html,
        "knowledge_point_ids": [
            knowledge_point.knowledge_point_id
            for knowledge_point in question.knowledge_points.all()
        ],
        "knowledge_point_version": question.knowledge_point_version,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
        "images": question.images,
        "audit_status": question.audit_status,
    }
    if match_score is not None:
        data["match_score"] = match_score
    return data
