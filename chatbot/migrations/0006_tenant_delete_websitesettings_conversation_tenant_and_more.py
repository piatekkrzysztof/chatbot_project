# Generated by Django 5.1.7 on 2025-03-26 10:38

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0005_websitesettings'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tenant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Nazwa klienta')),
                ('api_key', models.CharField(default=uuid.uuid4, max_length=100, unique=True, verbose_name='Klucz API')),
                ('owner_email', models.EmailField(max_length=254, verbose_name='Owner email')),
                ('gpt_prompt', models.TextField(default='Jesteś chatbotem z obsługi klienta', verbose_name='Prompt GPT')),
                ('regulamin', models.TextField(default='Treść regulaminu')),
            ],
        ),
        migrations.DeleteModel(
            name='WebsiteSettings',
        ),
        migrations.AddField(
            model_name='conversation',
            name='tenant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='conversations', to='chatbot.tenant'),
        ),
        migrations.AddField(
            model_name='faq',
            name='tenant',
            field=models.ForeignKey(default=None, on_delete=django.db.models.deletion.CASCADE, related_name='faqs', to='chatbot.tenant'),
            preserve_default=False,
        ),
    ]
