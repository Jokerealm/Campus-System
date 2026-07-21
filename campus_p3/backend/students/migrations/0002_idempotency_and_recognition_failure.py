from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("students", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="practiceanswer",
            name="idempotency_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="practiceanswer",
            name="mastery_snapshot",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="wrongquestion",
            name="idempotency_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="wrongquestion",
            name="recognition_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="wrongquestion",
            name="status",
            field=models.CharField(
                choices=[
                    ("uploaded", "Uploaded"),
                    ("recognizing", "Recognizing"),
                    ("recognition_failed", "Recognition failed"),
                    ("recognized", "Recognized"),
                    ("confirmed", "Confirmed"),
                    ("learning", "Learning"),
                    ("mastered", "Mastered"),
                ],
                default="uploaded",
                max_length=32,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="wrongquestion",
            name="students_wq_status_valid",
        ),
        migrations.AddConstraint(
            model_name="wrongquestion",
            constraint=models.CheckConstraint(
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
        ),
    ]
