import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from resources.models import QuestionBankItem
from resources.serializers import QuestionImportRequestSerializer
from resources.services import get_knowledge_points_by_public_ids


class Command(BaseCommand):
    help = "Load question bank seed data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=None,
            help="Path to the question bank JSON seed file.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        source = Path(options["source"]) if options["source"] else self._default_source()
        if not source.is_absolute():
            source = Path.cwd() / source
        if not source.exists():
            raise CommandError(f"Seed file not found: {source}")

        with source.open(encoding="utf-8") as file:
            raw_payload = json.load(file)
        batches = raw_payload if isinstance(raw_payload, list) else [raw_payload]

        created_count = 0
        updated_count = 0
        for batch_index, batch in enumerate(batches):
            serializer = QuestionImportRequestSerializer(data=batch)
            if not serializer.is_valid():
                raise CommandError(f"Batch {batch_index} is invalid: {serializer.errors}")
            payload = serializer.validated_data
            for item_index, item in enumerate(payload["items"]):
                if "bank_question_id" not in item:
                    raise CommandError(
                        f"Batch {batch_index} item {item_index} is missing bank_question_id."
                    )

            knowledge_point_map = self._get_validated_knowledge_points(
                batch_index,
                payload["items"],
                payload["knowledge_point_version"],
            )

            for item in payload["items"]:
                _, created = self._upsert_question(
                    source=payload["source"],
                    knowledge_point_version=payload["knowledge_point_version"],
                    item=item,
                    knowledge_point_map=knowledge_point_map,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {created_count + updated_count} questions: "
                f"{created_count} created, {updated_count} updated."
            )
        )

    def _default_source(self):
        return Path(__file__).resolve().parents[2] / "fixtures" / "question_bank_2026_1.json"

    def _get_validated_knowledge_points(self, batch_index, items, version):
        knowledge_point_ids = []
        for item in items:
            knowledge_point_ids.extend(item["knowledge_point_ids"])

        knowledge_point_map, missing_ids = get_knowledge_points_by_public_ids(
            knowledge_point_ids,
            version,
        )
        if missing_ids:
            raise CommandError(
                f"Batch {batch_index} has unknown knowledge point ids for version {version}: "
                f"{', '.join(missing_ids)}"
            )
        return knowledge_point_map

    def _upsert_question(self, source, knowledge_point_version, item, knowledge_point_map):
        question, created = QuestionBankItem.objects.update_or_create(
            bank_question_id=item["bank_question_id"],
            defaults={
                "source": source,
                "content_html": item["content_html"],
                "answer_html": item["answer_html"],
                "analysis_html": item["analysis_html"],
                "question_type": item["question_type"],
                "difficulty": item["difficulty"],
                "images": item.get("images", []),
                "audit_status": item["audit_status"],
                "knowledge_point_version": knowledge_point_version,
            },
        )
        question.knowledge_points.set(
            [
                knowledge_point_map[knowledge_point_id]
                for knowledge_point_id in item["knowledge_point_ids"]
            ]
        )
        return question, created
