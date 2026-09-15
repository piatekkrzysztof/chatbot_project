from django.contrib import admin

from chat.eksport_csv import strumien_csv
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

    @admin.action(description="Eksportuj zaznaczone do CSV")
    def export_as_csv(self, request, queryset):
        # Treść pisze odwiedzający, więc przez tę samą neutralizację formuł co
        # eksport w API - patrz chat/eksport_csv.py.
        wiersze = (
            [
                obj.tenant.name,
                obj.model,
                obj.source,
                obj.tokens,
                obj.prompt,
                obj.response or "",
                obj.created_at.isoformat(),
            ]
            for obj in queryset.select_related("tenant").iterator(chunk_size=1000)
        )
        return strumien_csv(
            "prompt_logs.csv",
            ["tenant", "model", "source", "tokens", "prompt", "response", "created_at"],
            wiersze,
        )

    @admin.display(description="Prompt (skrót)")
    def short_prompt(self, obj):
        return obj.prompt[:80] + "..." if len(obj.prompt) > 80 else obj.prompt

    @admin.display(description="Odpowiedź (skrót)")
    def short_response(self, obj):
        if obj.response:
            return obj.response[:80] + "..." if len(obj.response) > 80 else obj.response
        return "–"


@admin.register(ChatFeedback)
class ChatFeedbackAdmin(admin.ModelAdmin):
    list_display = ("message", "is_helpful", "submitted_at")
    list_filter = ("is_helpful",)
