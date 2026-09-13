from django.contrib import admin

from chat.eksport_csv import BezpiecznyWriter, odpowiedz_csv
from chat.models import FAQ, ChatFeedback, ContactRequest, PromptLog


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("tenant", "contact", "name", "handled", "created_at")
    list_filter = ("tenant", "handled")
    search_fields = ("contact", "name", "message")


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("tenant", "question")
    list_filter = ("tenant",)
    search_fields = ("question", "answer")


@admin.register(PromptLog)
class PromptLogAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "source",
        "model",
        "tokens",
        "short_prompt",
        "short_response",
        "created_at",
    )
    list_filter = ("source", "model", "tenant")
    search_fields = ("prompt", "response", "tenant__name", "model")
    readonly_fields = ("created_at", "prompt", "response")
    actions = ["export_as_csv"]

    def export_as_csv(self, request, queryset):
        # Treść pisze odwiedzający, więc przez tę samą neutralizację formuł co
        # eksport w API - patrz chat/eksport_csv.py.
        response = odpowiedz_csv("prompt_logs.csv")
        writer = BezpiecznyWriter(response)
        writer.writerow(["tenant", "model", "source", "tokens", "prompt", "response", "created_at"])
        for obj in queryset.select_related("tenant").iterator():
            writer.writerow(
                [
                    obj.tenant.name,
                    obj.model,
                    obj.source,
                    obj.tokens,
                    obj.prompt,
                    obj.response or "",
                    obj.created_at.isoformat(),
                ]
            )
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
