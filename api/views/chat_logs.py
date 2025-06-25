from rest_framework.generics import ListAPIView
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from chat.models import PromptLog, Tenant, ChatFeedback, ChatMessage
from api.serializers import PromptLogSerializer
from api.utils.mixins import TenantQuerysetMixin
from api.permissions import IsTenantMember


class PromptLogListView(TenantQuerysetMixin, ListAPIView):
    queryset = PromptLog.objects.all()
    serializer_class = PromptLogSerializer
    pagination_class = PageNumberPagination
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset().select_related("conversation").order_by("-created_at")
        is_helpful = self.request.query_params.get("is_helpful")

        if is_helpful is not None:
            is_helpful = is_helpful.lower() in ["true", "1"]

            helpful_messages = ChatFeedback.objects.filter(
                is_helpful=is_helpful
            ).select_related("message").values_list("message__message", flat=True)

            qs = qs.filter(response__in=helpful_messages)

        return qs
