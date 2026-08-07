from rest_framework import viewsets

from api.permissions import IsOwnerOrEmployee
from api.serializers import FAQSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.models import FAQ


class FAQViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    Zarządzanie FAQ z panelu klienta. Wpisy trafiają do kontekstu asystenta,
    więc klient może sam dopisać odpowiedzi na pytania, których bot nie znał.
    """
    queryset = FAQ.objects.all()
    serializer_class = FAQSerializer
    permission_classes = [IsOwnerOrEmployee]

    def get_queryset(self):
        return super().get_queryset().order_by("id")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
