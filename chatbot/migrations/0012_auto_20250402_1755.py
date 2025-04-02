from django.db import migrations


def set_default_tenant(apps, schema_editor):
    Tenant = apps.get_model('chatbot', 'Tenant')
    Conversation = apps.get_model('chatbot', 'Conversation')

    # utwórz lub pobierz domyślnego tenanta
    default_tenant, _ = Tenant.objects.get_or_create(
        name="Domyślny Tenant",
        defaults={
            'owner_email': 'default@example.com',
            'gpt_prompt': 'Domyślny prompt',
            'regulamin': 'Domyślny regulamin',
        }
    )

    # przypisz wszystkim istniejącym rozmowom domyślnego tenanta
    Conversation.objects.filter(tenant__isnull=True).update(tenant=default_tenant)


class Migration(migrations.Migration):
    dependencies = [
        ('chatbot', '0007_alter_conversation_tenant'),
    ]

    operations = [
        migrations.RunPython(set_default_tenant),
    ]
