# Generated by Django 5.1.7 on 2025-03-28 18:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0008_tenant_widget_color_tenant_widget_position_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='openai_api_key',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
