from rest_framework.generics import ListAPIView
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from chat.models import PromptLog, Tenant, ChatFeedback, ChatMessage
from api.serializers import PromptLogSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.zapytania import ZRODLO_TESTOWE
from api.permissions import IsTenantMember
from drf_spectacular.utils import extend_schema


@extend_schema(
    tags=["Panel — czat"],
    summary="Historia pytań i odpowiedzi",
    description="Zawiera identyfikator rozmowy, którym posługuje się usuwanie danych na żądanie.",
)
class PromptLogListView(TenantQuerysetMixin, ListAPIView):
    queryset = PromptLog.objects.all()
    serializer_class = PromptLogSerializer
    pagination_class = PageNumberPagination
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        # Rozmowy testowe właściciela nie są historią kontaktów z klientami
        # — na tej liście byłyby szumem, a w liczniku zawyżeniem.
        qs = (
            super()
            .get_queryset()
            .exclude(conversation__source=ZRODLO_TESTOWE)
            .select_related("conversation")
            .order_by("-created_at")
        )
        is_helpful = self.request.query_params.get("is_helpful")

        if is_helpful is not None:
            is_helpful = is_helpful.lower() in ["true", "1"]

            helpful_messages = (
                ChatFeedback.objects.filter(is_helpful=is_helpful)
                .select_related("message")
                .values_list("message__message", flat=True)
            )

            qs = qs.filter(response__in=helpful_messages)

        return qs
