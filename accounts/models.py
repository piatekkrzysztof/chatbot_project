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
