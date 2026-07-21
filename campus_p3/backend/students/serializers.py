from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from core.exceptions import FileTooLargeError, UnsupportedFileTypeError


IMAGE_SIGNATURES = {
    "image/png": lambda header: header.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda header: header.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda header: (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ),
}
IMAGE_EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
}


class WrongQuestionUploadSerializer(serializers.Serializer):
    student_id = serializers.CharField(allow_blank=False, max_length=64)
    subject = serializers.ChoiceField(choices=["math"])
    grade = serializers.CharField(allow_blank=False, max_length=16)
    image = serializers.FileField(allow_empty_file=False)

    def validate_image(self, uploaded_file):
        max_size = getattr(settings, "WRONG_QUESTION_MAX_FILE_SIZE", 10 * 1024 * 1024)
        if uploaded_file.size > max_size:
            raise FileTooLargeError(
                f"wrong-question image exceeds the {max_size}-byte limit"
            )

        allowed_types = set(
            getattr(
                settings,
                "WRONG_QUESTION_ALLOWED_CONTENT_TYPES",
                ["image/jpeg", "image/png", "image/webp"],
            )
        )
        content_type = getattr(uploaded_file, "content_type", "")
        if content_type not in allowed_types:
            raise UnsupportedFileTypeError(
                f"unsupported wrong-question image type: {content_type or 'unknown'}"
            )
        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS.get(content_type, set()):
            raise UnsupportedFileTypeError(
                "wrong-question file extension does not match its declared image type"
            )
        signature_validator = IMAGE_SIGNATURES.get(content_type)
        try:
            header = uploaded_file.read(16)
            uploaded_file.seek(0)
        except (AttributeError, OSError) as exc:
            raise UnsupportedFileTypeError(
                "wrong-question image could not be inspected"
            ) from exc
        if signature_validator is None or not signature_validator(header):
            raise UnsupportedFileTypeError(
                "wrong-question file content does not match its declared image type"
            )
        return uploaded_file


class WrongQuestionConfirmSerializer(serializers.Serializer):
    stem_html = serializers.CharField(allow_blank=False)
    question_type = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=64,
    )
    knowledge_point_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, max_length=64),
        allow_empty=False,
    )


class ExplanationNextSerializer(serializers.Serializer):
    current_step_index = serializers.IntegerField(min_value=0)
    student_input = serializers.CharField(required=False, allow_blank=True, default="")
    mode = serializers.ChoiceField(choices=["hint", "check", "explain", "summary"])


class PracticeRecommendationQuerySerializer(serializers.Serializer):
    student_id = serializers.CharField(allow_blank=False, max_length=64)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=5)


class PracticeAnswerRequestSerializer(serializers.Serializer):
    student_id = serializers.CharField(allow_blank=False, max_length=64)
    bank_question_id = serializers.CharField(allow_blank=False, max_length=64)
    answer_text = serializers.CharField(allow_blank=True)
    is_correct = serializers.BooleanField()
    used_seconds = serializers.IntegerField(min_value=0, max_value=86_400)
