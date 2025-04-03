import uuid

from django.db import models


class Tenant(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nazwa klienta")
    api_key = models.CharField(max_length=100, unique=True, default=uuid.uuid4, verbose_name="Klucz API")
    owner_email = models.EmailField(verbose_name="Owner email")
    gpt_prompt = models.TextField(default="Jesteś chatbotem z obsługi klienta", verbose_name="Prompt GPT")
    regulamin = models.TextField(default="Treść regulaminu")
    openai_api_key = models.CharField(max_length=255, blank=True, null=True)

    WIDGET_POSITIONS = [
        ('bottom-right', 'Dół strony (prawy)'),
        ('bottom-left', 'Dół strony (lewy)'),
        ('side-right', 'Boczny (prawy)'),
        ('side-left', 'Boczny (lewy)'),
        ('hamburger', 'Przycisk hamburger'),
    ]
    widget_position = models.CharField(
        max_length=20,
        choices=WIDGET_POSITIONS,
        default='bottom-right'
    )

    widget_color = models.CharField(max_length=7, default='#3b82f6')  # Tailwind blue-500 domyślnie
    widget_title = models.CharField(max_length=50, default='Chatbot')

    def __str__(self):
        return self.name
