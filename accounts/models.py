import uuid
from django.contrib.auth.models import AbstractUser

from django.utils import timezone
from datetime import timedelta

from django.db import models

WIDGET_POSITIONS = [
    ('bottom-right', 'Dół strony (prawy)'),
    ('bottom-left', 'Dół strony (lewy)'),
    ('side-right', 'Boczny (prawy)'),
    ('side-left', 'Boczny (lewy)'),
    ('hamburger', 'Przycisk hamburger'),
]

ROLE_CHOICES = [
    ('owner', 'Owner'),
    ('employee', 'Employee'),
    ('viewer', 'Viewer'),
]

DURATION_CHOICES = [
    (12, '12 godzin'),
    (24, '24 godziny'),
    (48, '48 godzin'),
]


class Tenant(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nazwa klienta")
    api_key = models.CharField(max_length=100, unique=True, default=uuid.uuid4, verbose_name="Klucz API")
    owner_email = models.EmailField(verbose_name="Owner email")
    created_at = models.DateTimeField(auto_now_add=True)

    # branding i ustawienia
    gpt_prompt = models.TextField(default="Jesteś chatbotem z obsługi klienta", verbose_name="Prompt GPT")
    regulamin = models.TextField(default="Treść regulaminu")
    widget_position = models.CharField(
        max_length=20,
        choices=WIDGET_POSITIONS,
        default='bottom-right'
    )
    widget_color = models.CharField(max_length=7, default='#3b82f6')  # Tailwind blue-500 domyślnie
    widget_title = models.CharField(max_length=50, default='Chatbot')

    # klucz OpenAI
    openai_api_key = models.CharField(max_length=255, blank=True, null=True)

    # Subskrypcje (do dokładniejszego wdrążenia)
    subscription_plan = models.CharField(max_length=50, default='free')
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)
    subscription_status = models.CharField(max_length=50, default='inactive')
    current_token_usage = models.PositiveIntegerField(default=0)
    token_limit = models.PositiveIntegerField(default=100_000)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    tenant = models.ForeignKey(Tenant, related_name='users', on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.username} ({self.tenant.name})"

    @property
    def is_owner(self):
        return self.role == 'owner'


class InvitationToken(models.Model):
    tenant = models.ForeignKey('Tenant', on_delete=models.CASCADE, related_name='invitations')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    created_at = models.DateTimeField(auto_now_add=True)
    duration_hours = models.IntegerField(choices=DURATION_CHOICES, default=24)
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    @property
    def expires_at(self):
        return self.created_at + timedelta(hours=self.duration_hours)

    def is_valid(self):
        now = timezone.now()
        return self.uses < self.max_uses and self.expires_at > now

    def use(self):
        if not self.is_valid():
            raise ValueError("Token is expired or fully used.")
        self.uses += 1
        self.save()

    def __str__(self):
        return f"{self.token} ({self.tenant.name})"
