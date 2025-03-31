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


class Conversation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='conversations')
    user_identifier = models.CharField(max_length=100)
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rozmowa{self.id} ({self.started_at.strftime('%Y-%m-%d %H:%M')})"


class ChatMessage(models.Model):
    conversation = models.ForeignKey(Conversation, related_name='messages', on_delete=models.CASCADE)
    sender = models.CharField(max_length=24)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender}: {self.message:50}..."


class FAQ(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='faqs')
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return self.question


class ChatUsageLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='usage_logs')
    tokens_used = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tenant.name} - {self.tokens_used} tokens at {self.created_at}"
