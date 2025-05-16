from rest_framework.generics import ListAPIView
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from chat.models import PromptLog, Tenant
from api.serializers import PromptLogSerializer
from api.utils.mixins import TenantQuerysetMixin


class PromptLogListView(TenantQuerysetMixin, ListAPIView):
    serializer_class = PromptLogSerializer
    pagination_class = PageNumberPagination

    def get_queryset(self):
        qs = super().get_queryset().select_related("conversation").order_by("-created_at")

        is_helpful = self.request.query_params.get("is_helpful")
        if is_helpful is not None:
            bool_value = is_helpful.lower() in ["true", "1"]
            qs = [log for log in qs if log.is_helpful == bool_value]

        return qs
