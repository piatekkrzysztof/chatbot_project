# Generated by Django 5.1.7 on 2025-06-18 13:25

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0007_conversation_session_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversation',
            name='session_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
