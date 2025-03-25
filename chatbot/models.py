from django.db import models


class Conversation(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    user_identifier = models.CharField(max_length=100)

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
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return self.question


class WebsiteSettings(models.Model):
    website_name = models.CharField(max_length=100, verbose_name="Nazwa strony")
    owner_email = models.EmailField(verbose_name="Email właściciela")
    gpt_prompt = models.TextField(
        default="Jesteś chatbotem obsługującym klientów sklepu internetowego.",
        verbose_name="Prompt GPT"
    )

    def __str__(self):
        return self.website_name
