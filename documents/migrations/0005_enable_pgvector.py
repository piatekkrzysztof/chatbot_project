from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0004_documentchunk"),
    ]

    operations = [
        migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS vector;")
    ]