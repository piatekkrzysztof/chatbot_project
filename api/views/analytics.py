from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsTenantMember
from drf_spectacular.utils import extend_schema

from api.schemas import AnalyticsSerializer
from chat.models import Conversation, ChatMessage, PromptLog, FAQ
from documents.models import Document, DocumentChunk, WebsiteSource


UNANSWERED_LIMIT = 20


def knowledge_summary(tenant):
    """
    Czym bot realnie dysponuje, odpowiadając klientom.

    Bez żadnego z tych źródeł bot odmawia odpowiedzi na każde pytanie o firmę —
    celowo, żeby nie zmyślał. Panel musi to pokazać wprost, inaczej właściciel
    widzi tylko bota, który "nic nie umie", i nie wie, że brakuje mu materiałów.
    """
    documents = Document.objects.filter(tenant=tenant).count()
    chunks = DocumentChunk.objects.filter(document__tenant=tenant).count()
    faqs = FAQ.objects.filter(tenant=tenant).count()
    websites = WebsiteSource.objects.filter(tenant=tenant).count()
    has_description = bool(tenant.gpt_prompt and tenant.gpt_prompt.strip())

    return {
        "has_description": has_description,
        "documents": documents,
        "indexed_chunks": chunks,
        "faqs": faqs,
        "websites": websites,
        # Dokument bez fragmentów jeszcze się nie przetworzył i nie liczy się jako wiedza
        "is_empty": not (has_description or chunks or faqs),
    }


@extend_schema(
    tags=["Panel — analityka"],
    summary="Podsumowanie działania chatbota",
    description=(
        "Liczby rozmów i pytań, pokrycie odpowiedzi materiałami firmy, zużycie "
        "planu oraz lista pytań, na które bot nie miał pokrycia."
    ),
    responses={200: AnalyticsSerializer},
)
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
            "knowledge": knowledge_summary(tenant),
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
