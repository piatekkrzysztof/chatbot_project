from django.db import models
from accounts.models import Tenant
from django.utils import timezone
from accounts.models import Client  # Import nowego modelu Client
import uuid


class Conversation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='conversations')
    user_identifier = models.CharField(max_length=100)
    started_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, default='active')  # active, closed, archived
    source = models.CharField(max_length=30, default='widget')  # widget, panel, API

    class Meta:
        ordering = ['-last_message_at']

    def __str__(self):
        return f"Conversation {self.id} ({self.tenant.name})"


class ChatMessage(models.Model):
    SENDER_CHOICES = [
        ('user', 'User'),
        ('bot', 'Bot'),
        ('system', 'System'),
    ]

    SOURCE_CHOICES = [
        ('faq', 'FAQ'),
        ('document', 'Document'),
        ('gpt', 'OpenAI'),
        ('fallback', 'Fallback'),
        ('manual', 'Manual')
    ]

    conversation = models.ForeignKey(Conversation, related_name='messages', on_delete=models.CASCADE)
    sender = models.CharField(max_length=24, choices=SENDER_CHOICES)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    # Rozszerzenia
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='gpt')
    token_count = models.PositiveIntegerField(default=0, help_text="Liczba tokenów tej wiadomości (jeśli dotyczy)")

    def __str__(self):
        return f"{self.sender.title()}: {self.message[:50]}"


class FAQ(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='faqs')
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return f"FAQ ({self.tenant.name}): {self.question[:50]}"


class ChatUsageLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='usage_logs')
    created_at = models.DateTimeField(auto_now_add=True)
    tokens_used = models.PositiveIntegerField()
    model_used = models.CharField(max_length=50, default='gpt-3.5-turbo')
    source = models.CharField(max_length=20, choices=ChatMessage.SOURCE_CHOICES, default='gpt')
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.tenant.name} - {self.tokens_used} tokens on {self.model_used} ({self.source})"


class PromptLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)
    model = models.CharField(max_length=50)
    prompt = models.TextField()
    source = models.CharField(max_length=50, choices=[
        ("faq", "FAQ"),
        ("document", "RAG"),
        ("gpt", "GPT fallback")
    ])
    tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    response = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.model}] ({self.source}) {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class ChatFeedback(models.Model):
    message = models.OneToOneField(ChatMessage, on_delete=models.CASCADE, related_name="feedback")
    is_helpful = models.BooleanField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.message.id}: {'👍' if self.is_helpful else '👎'}"





class Chat(models.Model):
    # Powiązanie z konfiguracją klienta
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name='chats',
        verbose_name="Konfiguracja Chatbota"
    )

    # Identyfikator sesji
    session_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="ID Sesji"
    )

    # Dane użytkownika końcowego (anonimowe)
    user_ip = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name="IP użytkownika"
    )
    user_agent = models.TextField(
        blank=True,
        verbose_name="Przeglądarka użytkownika"
    )

    # Status konwersacji
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktywna sesja"
    )

    # Automatyczne znaczniki czasu
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Chat: {self.client.name} ({self.started_at})"

    class Meta:
        verbose_name = "Sesja Chat"
        verbose_name_plural = "Sesje Chatów"
        indexes = [
            models.Index(fields=['session_id']),
            models.Index(fields=['client', 'started_at']),
        ]
