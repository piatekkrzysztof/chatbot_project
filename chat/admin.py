import csv

from django.contrib import admin
from chat.models import PromptLog, ChatFeedback
from django.http import HttpResponse

@admin.register(PromptLog)
class PromptLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "source", "model", "tokens", "short_prompt", "short_response", "created_at")
    list_filter = ("source", "model", "tenant")
    search_fields = ("prompt", "response", "tenant__name", "model")
    readonly_fields = ("created_at", "prompt", "response")
    actions = ["export_as_csv"]

    def export_as_csv(self, request, queryset):
        fieldnames = ["tenant", "model", "source", "tokens", "prompt", "response", "created_at"]
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=prompt_logs.csv"
        writer = csv.DictWriter(response, fieldnames=fieldnames)
        writer.writeheader()
        for obj in queryset:
            writer.writerow({
                "tenant": obj.tenant.name,
                "model": obj.model,
                "source": obj.source,
                "tokens": obj.tokens,
                "prompt": obj.prompt,
                "response": obj.response or "",
                "created_at": obj.created_at.isoformat()
            })
        return response

    export_as_csv.short_description = "Eksportuj zaznaczone do CSV"

    def short_prompt(self, obj):
        return obj.prompt[:80] + "..." if len(obj.prompt) > 80 else obj.prompt

    def short_response(self, obj):
        if obj.response:
            return obj.response[:80] + "..." if len(obj.response) > 80 else obj.response
        return "–"

    short_prompt.short_description = "Prompt (skrót)"
    short_response.short_description = "Odpowiedź (skrót)"

@admin.register(ChatFeedback)
class ChatFeedbackAdmin(admin.ModelAdmin):
    list_display = ("message", "is_helpful", "submitted_at")
    list_filter = ("is_helpful",)
