import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from resources.models import KnowledgePoint


class Command(BaseCommand):
    help = "Load knowledge point seed data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=None,
            help="Path to the knowledge point JSON seed file.",
        )
        parser.add_argument(
            "--knowledge-version",
            default=KnowledgePoint.DEFAULT_VERSION,
            help="Version to load when an item does not specify one.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        source = Path(options["source"]) if options["source"] else self._default_source()
        if not source.is_absolute():
            source = Path.cwd() / source
        if not source.exists():
            raise CommandError(f"Seed file not found: {source}")

        with source.open(encoding="utf-8") as file:
            items = json.load(file)
        if not isinstance(items, list):
            raise CommandError("Seed file must contain a JSON array.")

        created_count = 0
        updated_count = 0
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise CommandError(f"Item at index {index} must be an object.")
            knowledge_point_id = self._required_field(item, "knowledge_point_id", index)
            version = item.get("version", options["knowledge_version"])
            if not version:
                raise CommandError(f"Item at index {index} is missing version.")

            defaults = {
                "code": self._required_field(item, "code", index),
                "name": self._required_field(item, "name", index),
                "parent_id": item.get("parent_id"),
                "subject": self._required_field(item, "subject", index),
                "stage": self._required_field(item, "stage", index),
                "grade_range": item.get("grade_range", []),
                "path": item.get("path", []),
                "enabled": item.get("enabled", True),
                "sort_order": item.get("sort_order", index),
            }
            _, created = KnowledgePoint.objects.update_or_create(
                knowledge_point_id=knowledge_point_id,
                version=version,
                defaults=defaults,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(items)} knowledge points: {created_count} created, {updated_count} updated."
            )
        )

    def _default_source(self):
        return Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_points_2026_1.json"

    def _required_field(self, item, field_name, index):
        value = item.get(field_name)
        if value in (None, ""):
            raise CommandError(f"Item at index {index} is missing {field_name}.")
        return value
