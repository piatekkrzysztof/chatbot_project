# Generated by Django 5.1.7 on 2025-05-06 18:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_alter_invitationtoken_options_alter_tenant_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='gpt_prompt',
            field=models.TextField(blank=True, help_text="Unikalny prompt charakterystyczny dla firmy (np. 'Jesteśmy hurtownią elektryczną...')", null=True),
        ),
    ]
