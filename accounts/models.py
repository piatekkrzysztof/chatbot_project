import uuid
from datetime import timedelta
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator


class WidgetPosition(models.TextChoices):
    RIGHT = "right", "Right"
    LEFT = "left", "Left"


class UserRole(models.TextChoices):
    OWNER = "owner", "Owner"
    EMPLOYEE = "employee", "Employee"
    VIEWER = "viewer", "Viewer"


class InvitationDuration(models.TextChoices):
    ONE_HOUR = "1h", "1 Hour"
    TWELVE_HOURS = "12h", "12 Hours"
    ONE_DAY = "1d", "1 Day"
    ONE_WEEK = "7d", "7 Days"


class Tenant(models.Model):
    name = models.CharField(max_length=100)
    api_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    regulamin = models.TextField(blank=True, null=True)
    gpt_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="Unikalny prompt charakterystyczny dla firmy (np. 'Jesteśmy hurtownią elektryczną...')"
    )

    # OpenAI
    openai_api_key = models.CharField(max_length=128, blank=True, null=True)

    # Widget
    widget_position = models.CharField(max_length=10, choices=WidgetPosition.choices, default=WidgetPosition.RIGHT)
    widget_color = models.CharField(max_length=20, default="#000000")
    widget_title = models.CharField(max_length=100, default="Chatbot")

    # Email
    owner_email = models.EmailField(blank=True, null=True)

    # Subskrypcje
    subscription_plan = models.CharField(max_length=100, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_status = models.CharField(max_length=50, blank=True, null=True)

    # Token
    current_token_usage = models.PositiveIntegerField(default=0)
    token_limit = models.PositiveIntegerField(default=100000, validators=[MinValueValidator(1000)])

    created_at = models.DateTimeField(auto_now_add=True)

    def has_active_subscription(self):
        return self.subscription_status in ["active", "trialing"]

    def token_limit_exceeded(self):
        return self.current_token_usage >= self.token_limit

    def __str__(self):
        return f"{self.name} (API Key: {self.api_key})"


class CustomUser(AbstractUser):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="users")
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.VIEWER)

    def __str__(self):
        return f"{self.username} [{self.tenant.name}]"


class InvitationToken(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.EMPLOYEE)
    duration = models.CharField(max_length=10, choices=InvitationDuration.choices, default=InvitationDuration.ONE_DAY)
    created_at = models.DateTimeField(auto_now_add=True)
    max_users = models.PositiveIntegerField(default=1)
    users = models.PositiveIntegerField(default=0)

    @property
    def expires_at(self):
        delta = {
            "1h": timedelta(hours=1),
            "12h": timedelta(hours=12),
            "1d": timedelta(days=1),
            "7d": timedelta(days=7),
        }.get(self.duration, timedelta(days=1))
        return self.created_at + delta

    def is_valid(self):
        delta = {
            "1h": timedelta(hours=1),
            "12h": timedelta(hours=12),
            "1d": timedelta(days=1),
            "7d": timedelta(days=7),
        }.get(self.duration, timedelta(days=1))
        return self.created_at + delta > timezone.now() and self.users < self.max_users

    def use(self):
        self.users += 1
        self.save()

    def __str__(self):
        return f"Invitation for {self.email} [{self.role}] ({self.tenant.name})"


class Client(models.Model):
    # Powiązania
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='clients',
        verbose_name="Firma kliencka"
    )
    created_by = models.ForeignKey(
        'CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Twórca konfiguracji"
    )

    # Pola podstawowe
    name = models.CharField(
        max_length=100,
        verbose_name="Nazwa konfiguracji",
        help_text="Np. 'Chatbot Sklepu Głównego'"
    )
    website_url = models.URLField(
        verbose_name="Adres URL strony",
        help_text="Gdzie zostanie osadzony chatbot"
    )

    # Autogenerowany klucz API
    api_key = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="Klucz API"
    )

    # Konfiguracja chatbota w formacie JSON
    chatbot_config = models.JSONField(
        default=dict,
        verbose_name="Konfiguracja",
        help_text="Ustawienia chatbota w formacie JSON"
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktywny"
    )

    # Automatyczne znaczniki czasu
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

    class Meta:
        verbose_name = "Konfiguracja Chatbota"
        verbose_name_plural = "Konfiguracje Chatbotów"
        unique_together = ['tenant', 'name']


class Subscription(models.Model):
    # Istniejące pola (przykład - dostosuj do twojej implementacji)
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan_type = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    # Nowe pola dla limitów
    message_limit = models.PositiveIntegerField(
        default=1000,
        verbose_name="Limit wiadomości/miesiąc",
        help_text="Miesięczny limit wiadomości dla wszystkich chatbotów firmy"
    )

    current_message_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Liczba użytych wiadomości"
    )

    # Cykl rozliczeniowy
    billing_cycle_start = models.DateField(
        auto_now_add=True,
        verbose_name="Start cyklu rozliczeniowego"
    )

    # Metody walidacyjne
    def has_message_quota(self):
        """Czy firma ma dostępne wiadomości w bieżącym cyklu"""
        return self.current_message_count < self.message_limit

    def reset_usage(self):
        """Resetuj licznik na początku nowego cyklu"""
        self.current_message_count = 0
        self.billing_cycle_start = timezone.now().date()
        self.save(update_fields=['current_message_count', 'billing_cycle_start'])

    def increment_usage(self):
        """Atomowe zwiększenie licznika wiadomości"""
        Subscription.objects.filter(
            pk=self.pk
        ).update(
            current_message_count=models.F('current_message_count') + 1
        )
        self.refresh_from_db()
