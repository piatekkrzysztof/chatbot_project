from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsTenantMember
from chat.models import Conversation, ChatMessage, PromptLog


UNANSWERED_LIMIT = 20


class TenantAnalyticsView(APIView):
    """
    Podsumowanie aktywności chatbota dla panelu klienta: ile rozmów, ile pytań,
    ile zostało z limitu planu i — najważniejsze — o co pytano, gdy bot nie miał
    pokrycia w materiałach firmy.
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        tenant = request.user.tenant
        now = timezone.now()
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        conversations = Conversation.objects.filter(tenant=tenant)
        messages = ChatMessage.objects.filter(conversation__tenant=tenant)
        logs = PromptLog.objects.filter(tenant=tenant)

        # Skąd pochodziły odpowiedzi — 'gpt' oznacza brak trafienia w dokumenty i FAQ
        by_source = {
            row["source"]: row["count"]
            for row in logs.values("source").annotate(count=Count("id"))
        }

        unanswered = (
            logs.filter(source="gpt")
            .order_by("-created_at")
            .values("id", "prompt", "created_at")[:UNANSWERED_LIMIT]
        )

        subscription = getattr(tenant, "subscription", None)

        return Response({
            "conversations": {
                "total": conversations.count(),
                "last_7d": conversations.filter(started_at__gte=last_7d).count(),
                "last_30d": conversations.filter(started_at__gte=last_30d).count(),
            },
            "questions": {
                "total": messages.filter(sender="user").count(),
                "last_7d": messages.filter(sender="user", timestamp__gte=last_7d).count(),
            },
            "answer_sources": {
                "document": by_source.get("document", 0),
                "faq": by_source.get("faq", 0),
                "gpt": by_source.get("gpt", 0),
            },
            "usage": {
                "used": subscription.current_message_count if subscription else 0,
                "limit": subscription.message_limit if subscription else None,
                "plan": subscription.plan_type if subscription else None,
            },
            "unanswered": [
                {
                    "id": row["id"],
                    "question": row["prompt"],
                    "asked_at": row["created_at"],
                }
                for row in unanswered
            ],
        })
