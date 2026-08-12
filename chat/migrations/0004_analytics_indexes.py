from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0003_contactrequest"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="conversation",
            index=models.Index(
                fields=["tenant", "started_at"],
                name="conv_tenant_started_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="chatmessage",
            index=models.Index(
                fields=["sender", "timestamp"],
                name="msg_sender_time_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="promptlog",
            index=models.Index(
                fields=["tenant", "source", "-created_at"],
                name="prompt_tenant_src_time_idx",
            ),
        ),
    ]
