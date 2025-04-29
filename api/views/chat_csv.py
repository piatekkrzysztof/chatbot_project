from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
import csv
from io import TextIOWrapper
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework import status
from chat.models import PromptLog, Tenant, Conversation


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


class ImportPromptLogsCSVView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("Brak klucza API.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Niepoprawny klucz API.")

        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"error": "Brak pliku CSV."}, status=status.HTTP_400_BAD_REQUEST)

        decoded = TextIOWrapper(csv_file.file, encoding="utf-8")
        reader = csv.DictReader(decoded)

        created = 0
        for row in reader:
            if not row.get("prompt") or not row.get("response"):
                continue  # pomiń niekompletne wiersze

            conv, _ = Conversation.objects.get_or_create(
                tenant=tenant,
                user_identifier="imported"
            )

            PromptLog.objects.create(
                tenant=tenant,
                conversation=conv,
                prompt=row["prompt"],
                response=row["response"],
                tokens=0,
                source="imported",
                model="manual"
            )
            created += 1

        return Response({"imported": created}, status=status.HTTP_201_CREATED)
