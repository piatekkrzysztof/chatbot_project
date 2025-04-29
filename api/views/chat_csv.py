import csv
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from chat.models import PromptLog, Tenant


class ExportPromptLogsCSVView(APIView):
    def get(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("Brak klucza API.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Niepoprawny klucz API.")

        logs = PromptLog.objects.filter(tenant=tenant).order_by("-created_at")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="prompt_logs_{tenant.id}.csv"'

        writer = csv.writer(response)
        writer.writerow(["conversation_id", "prompt", "response", "tokens", "source", "model", "created_at"])

        for log in logs:
            writer.writerow([
                log.conversation.id,
                log.prompt,
                log.response,
                log.tokens,
                log.source,
                log.model,
                log.created_at.isoformat()
            ])

        return response
