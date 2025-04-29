from rest_framework.generics import ListAPIView
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from chat.models import PromptLog, Tenant
from api.serializers import PromptLogSerializer


class PromptLogListView(ListAPIView):
    serializer_class = PromptLogSerializer
    pagination_class = PageNumberPagination

    def get_queryset(self):
        api_key = self.request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("API key missing.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Invalid API key.")

        qs = PromptLog.objects.filter(tenant=tenant).select_related("conversation").order_by("-created_at")

        is_helpful = self.request.query_params.get("is_helpful")
        if is_helpful is not None:
            bool_value = is_helpful.lower() in ["true", "1"]
            qs = list(qs)

            filtered = []
            for log in qs:
                if log.is_helpful == bool_value:
                    filtered.append(log)
            return filtered

        return qs
