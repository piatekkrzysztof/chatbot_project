from django.db import models
from accounts.models import Tenant
from django.utils import timezone
import uuid


class Conversation(models.Model):
    id = models.BigAutoField(primary_key=True)
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="conversations")
    user_identifier = models.CharField(max_length=100)
    started_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, default="active")  # active, closed, archived
    source = models.CharField(max_length=30, default="widget")  # widget, panel, API

    class Meta:
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(
                fields=["tenant", "started_at"],
                name="conv_tenant_started_idx",
            ),
        ]

    def __str__(self):
        return f"Conversation {self.id} ({self.tenant.name})"


class ChatMessage(models.Model):
    SENDER_CHOICES = [
        ("user", "User"),
        ("bot", "Bot"),
        ("system", "System"),
    ]

    SOURCE_CHOICES = [
        ("faq", "FAQ"),
        ("document", "Document"),
        ("gpt", "OpenAI"),
        ("fallback", "Fallback"),
        ("manual", "Manual"),
    ]

    conversation = models.ForeignKey(
        Conversation, related_name="messages", on_delete=models.CASCADE
    )
    sender = models.CharField(max_length=24, choices=SENDER_CHOICES)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    # Rozszerzenia
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="gpt")
    token_count = models.PositiveIntegerField(
        default=0, help_text="Liczba tokenów tej wiadomości (jeśli dotyczy)"
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["sender", "timestamp"],
                name="msg_sender_time_idx",
            ),
        ]

    def __str__(self):
        return f"{self.sender.title()}: {self.message[:50]}"


class FAQ(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="faqs")
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return f"FAQ ({self.tenant.name}): {self.question[:50]}"


class ChatUsageLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="usage_logs")
    created_at = models.DateTimeField(auto_now_add=True)
    tokens_used = models.PositiveIntegerField()
    model_used = models.CharField(max_length=50, default="gpt-3.5-turbo")
    source = models.CharField(max_length=20, choices=ChatMessage.SOURCE_CHOICES, default="gpt")
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return (
            f"{self.tenant.name} - {self.tokens_used} tokens on {self.model_used} ({self.source})"
        )


class PromptLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)
    model = models.CharField(max_length=50)
    prompt = models.TextField()
    source = models.CharField(
        max_length=50, choices=[("faq", "FAQ"), ("document", "RAG"), ("gpt", "GPT fallback")]
    )
    tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    response = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "source", "-created_at"],
                name="prompt_tenant_src_time_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.model}] ({self.source}) {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class ContactRequest(models.Model):
    """
    Prośba o kontakt zostawiona przez odwiedzającego, gdy bot nie potrafił pomóc.
    Bez tego rozmowa kończy się ślepym zaułkiem, a firma traci zapytanie.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="contact_requests")
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_requests",
    )
    name = models.CharField(max_length=100, blank=True)
    contact = models.CharField(max_length=200, help_text="E-mail lub telefon")
    message = models.TextField(blank=True)
    handled = models.BooleanField(default=False, verbose_name="Obsłużone")
    created_at = models.DateTimeField(auto_now_add=True)

    # Czy firma została powiadomiona. Wysyłka szła dotąd z fail_silently=True
    # opakowanym dodatkowo w try/except — awaria poczty nie zostawiała żadnego
    # śladu. Klient nie dostawał maila i nie miał jak się dowiedzieć, że go
    # nie dostał; zapytanie leżało w panelu, do którego nikt nie zaglądał.
    powiadomiono_at = models.DateTimeField(null=True, blank=True)
    blad_powiadomienia = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Kontakt od {self.contact} ({self.tenant.name})"


class ChatFeedback(models.Model):
    message = models.OneToOneField(ChatMessage, on_delete=models.CASCADE, related_name="feedback")
    is_helpful = models.BooleanField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.message.id}: {'👍' if self.is_helpful else '👎'}"
