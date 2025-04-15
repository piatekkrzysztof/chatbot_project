from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_documentchunk"),
    ]

    operations = [
        VectorExtension(),
    ]
