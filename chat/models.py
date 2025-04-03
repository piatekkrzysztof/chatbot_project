from django.db import models

from accounts.models import Tenant


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
