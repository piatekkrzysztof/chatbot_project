from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0014_private_document_storage")]

    operations = [
        migrations.AddField(
            model_name="document",
            name="processing_error",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
    ]
