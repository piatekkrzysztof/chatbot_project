from django.contrib import admin
from chat.models import PromptLog

@admin.register(PromptLog)
class PromptLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "source", "model", "tokens", "short_prompt", "short_response", "created_at")
    list_filter = ("source", "model", "tenant")
    search_fields = ("prompt", "response", "tenant__name", "model")
    readonly_fields = ("created_at", "prompt", "response")

    def short_prompt(self, obj):
        return obj.prompt[:80] + "..." if len(obj.prompt) > 80 else obj.prompt

    def short_response(self, obj):
        if obj.response:
            return obj.response[:80] + "..." if len(obj.response) > 80 else obj.response
        return "–"

    short_prompt.short_description = "Prompt (skrót)"
    short_response.short_description = "Odpowiedź (skrót)"
