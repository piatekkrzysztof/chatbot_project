from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsTenantMember
from drf_spectacular.utils import extend_schema

from api.schemas import AnalyticsSerializer
from chat.models import Conversation, ChatMessage, PromptLog, FAQ
from chat.raport_luk import luki_w_wiedzy
from chat.zapytania import logi_klientow, rozmowy_klientow, wiadomosci_klientow
from documents.models import Document, DocumentChunk, WebsiteSource


UNANSWERED_LIMIT = 20

# Okno listy luk na pulpicie. Wcześniej brana była cała historia konta, co przy
# dłużej działającym bocie zamieniało "szanse na poprawę" w archiwum: na górze
# siedziały pytania sprzed pół roku, dawno nieaktualne. Trzydzieści dni to
# zarazem to samo okno, którym mierzone są pozostałe liczby na pulpicie.
OKNO_LUK_DNI = 30


def knowledge_summary(tenant):
    """
    Czym bot realnie dysponuje, odpowiadając klientom.

    Bez żadnego z tych źródeł bot odmawia odpowiedzi na każde pytanie o firmę —
    celowo, żeby nie zmyślał. Panel musi to pokazać wprost, inaczej właściciel
    widzi tylko bota, który "nic nie umie", i nie wie, że brakuje mu materiałów.
    """
    document_stats = Document.objects.filter(tenant=tenant).aggregate(
        documents=Count("id", distinct=True),
        chunks=Count("chunks"),
    )
    documents = document_stats["documents"]
    chunks = document_stats["chunks"]
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
        cache_key = f"tenant-analytics:v2:{tenant.pk}"
        use_shared_cache = getattr(settings, "USE_SHARED_CACHE", False)
        if use_shared_cache:
            cached_payload = cache.get(cache_key)
            if cached_payload is not None:
                return Response(cached_payload)

        now = timezone.now()
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)
        today = timezone.localdate()
        first_chart_day = today - timedelta(days=6)
        chart_start = timezone.make_aware(
            datetime.combine(first_chart_day, time.min),
            timezone.get_current_timezone(),
        )

        # Rozmowy testowe właściciela to nie ruch klientów — w statystykach
        # zawyżałyby wszystko i psuły jedyne liczby mówiące coś o rynku.
        conversations = rozmowy_klientow(tenant)
        messages = wiadomosci_klientow(tenant).filter(sender="user")
        logs = logi_klientow(tenant)

        conversation_counts = conversations.aggregate(
            total=Count("id"),
            last_7d=Count("id", filter=Q(started_at__gte=last_7d)),
            last_30d=Count("id", filter=Q(started_at__gte=last_30d)),
        )
        question_counts = messages.aggregate(
            total=Count("id"),
            last_7d=Count("id", filter=Q(timestamp__gte=last_7d)),
        )

        daily_question_counts = {
            row["day"]: row["count"]
            for row in (
                messages.filter(timestamp__gte=chart_start)
                .annotate(day=TruncDate("timestamp"))
                .values("day")
                .annotate(count=Count("id"))
                .order_by("day")
            )
        }

        # Skąd pochodziły odpowiedzi — 'gpt' oznacza brak trafienia w dokumenty i FAQ
        by_source = {
            row["source"]: row["count"] for row in logs.values("source").annotate(count=Count("id"))
        }

        # Wspólne z raportem tygodniowym: jedna definicja tego, co liczy się
        # jako luka, i jedna zasada sklejania powtórzeń. Przy dwóch
        # implementacjach pulpit i mail prędzej czy później zaczęłyby pokazywać
        # co innego, a klient nie miałby jak rozstrzygnąć, które kłamie.
        unanswered = luki_w_wiedzy(
            tenant,
            od=timezone.now() - timedelta(days=OKNO_LUK_DNI),
            limit=UNANSWERED_LIMIT,
        )

        subscription = getattr(tenant, "subscription", None)

        payload = {
            "tenant_name": tenant.name,
            "knowledge": knowledge_summary(tenant),
            "conversations": conversation_counts,
            "questions": {
                **question_counts,
                "daily": [
                    {
                        "date": (first_chart_day + timedelta(days=offset)).isoformat(),
                        "count": daily_question_counts.get(
                            first_chart_day + timedelta(days=offset),
                            0,
                        ),
                    }
                    for offset in range(7)
                ],
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
                    "question": pozycja["pytanie"],
                    # Ile razy padło to samo pytanie. To ta liczba mówi, co
                    # uzupełnić najpierw — bez niej lista dziesięciu wpisów
                    # wygląda na dziesięć problemów, także gdy jest jednym.
                    "count": pozycja["ile"],
                    "asked_at": pozycja["ostatnio"],
                }
                for pozycja in unanswered
            ],
        }

        if use_shared_cache:
            cache.set(
                cache_key,
                payload,
                timeout=getattr(settings, "ANALYTICS_CACHE_SECONDS", 15),
            )

        return Response(payload)
