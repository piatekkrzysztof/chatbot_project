from rest_framework.generics import ListAPIView
from chat.models import PromptLog, Tenant
from api.serializers import PromptLogSerializer
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination


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

        qs = PromptLog.objects.filter(
            tenant=tenant
        ).select_related("conversation").order_by("-created_at")

        is_helpful_param = self.request.query_params.get("is_helpful")
        if is_helpful_param is not None:
            bool_val = is_helpful_param.lower() in ["true", "1"]
            from chat.models import ChatMessage
            filtered = []
            for log in qs:
                msg = ChatMessage.objects.filter(
                    conversation=log.conversation,
                    sender="bot",
                    message=log.response
                ).first()
                feedback = getattr(msg, "feedback", None)
                if feedback and feedback.is_helpful == bool_val:
                    filtered.append(log)
            return filtered

        return qs
