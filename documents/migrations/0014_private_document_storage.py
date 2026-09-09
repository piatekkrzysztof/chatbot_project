import documents.storage
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0013_wektor_512_wymiarow")]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(
                blank=True, null=True,
                storage=documents.storage.DocumentStorage(),
                upload_to=documents.storage.private_document_name,
            ),
        ),
    ]
