from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView

from api.pagination import StronicowaniePanelu
from api.permissions import IsTenantMember
from api.serializers import PromptLogSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.models import ChatMessage, PromptLog
from chat.zapytania import ZRODLO_TESTOWE


def z_ocena(queryset):
    """
    Ocena odpowiedzi dołączona jednym podzapytaniem, a nie osobnym zapytaniem na wiersz.

    Reguła bez zmian: najstarsza wiadomość bota w tej samej rozmowie z identyczną
    treścią i jej ocena. Wcześniej serializer szukał jej osobno dla każdego wpisu,
    więc strona historii kosztowała tyle zapytań, ile miała wierszy.
    """
    wiadomosc = ChatMessage.objects.filter(
        conversation=OuterRef("conversation"), sender="bot", message=OuterRef("response")
    ).order_by("pk")
    return queryset.annotate(ocena=Subquery(wiadomosc.values("feedback__is_helpful")[:1]))


@extend_schema(
    tags=["Panel — czat"],
    summary="Historia pytań i odpowiedzi",
    description="Zawiera identyfikator rozmowy, którym posługuje się usuwanie danych na żądanie.",
)
class PromptLogListView(TenantQuerysetMixin, ListAPIView):
    queryset = PromptLog.objects.all()
    serializer_class = PromptLogSerializer
    pagination_class = StronicowaniePanelu
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        # Rozmowy testowe właściciela nie są historią kontaktów z klientami
        # — na tej liście byłyby szumem, a w liczniku zawyżeniem.
        qs = z_ocena(
            super()
            .get_queryset()
            .exclude(conversation__source=ZRODLO_TESTOWE)
            .select_related("conversation")
            .order_by("-created_at", "-id")
        )
        is_helpful = self.request.query_params.get("is_helpful")

        if is_helpful is not None:
            # Po ocenie tej rozmowy. Wcześniej filtr porównywał odpowiedź z treścią
            # ocenionych wiadomości ze WSZYSTKICH firm: identyczna odpowiedź
            # oceniona u kogoś innego trafiała na listę, a podzapytanie rosło
            # z liczbą ocen w całym systemie.
            qs = qs.filter(ocena=is_helpful.lower() in ["true", "1"])

        return qs
