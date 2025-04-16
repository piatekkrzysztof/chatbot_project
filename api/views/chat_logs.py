from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from chat.models import PromptLog, ChatMessage, Tenant
from api.throttles import APIKeyRateThrottle


class PromptLogListView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def get(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("API key missing.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Invalid API key.")

        logs_qs = PromptLog.objects.filter(
            tenant=tenant
        ).select_related("conversation").order_by("-created_at")

        paginator = PageNumberPagination()
        paginated_logs = paginator.paginate_queryset(logs_qs, request, view=self)

        data = []
        is_helpful_filter = request.query_params.get("is_helpful")

        for log in paginated_logs:
            msg = ChatMessage.objects.filter(
                conversation=log.conversation,
                sender="bot",
                message=log.response
            ).first()

            feedback = getattr(msg, "feedback", None)
            is_helpful = feedback.is_helpful if feedback else None

            # jeśli user podał filtr, a feedback nie pasuje — pomijamy
            if is_helpful_filter is not None:
                filter_bool = is_helpful_filter.lower() in ["true", "1"]
                if is_helpful != filter_bool:
                    continue

            data.append({
                "id": log.id,
                "created_at": log.created_at,
                "model": log.model,
                "source": log.source,
                "tokens": log.tokens,
                "prompt": log.prompt,
                "response": log.response,
                "is_helpful": is_helpful
            })

        return paginator.get_paginated_response(data)
