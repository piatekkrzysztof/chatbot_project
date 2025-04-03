from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Tenant
from documents.models import Document
from api.serializers import DocumentSerializer
from documents.utils.file_to_text import extract_text
from django.conf import settings


class DocumentUploadView(APIView):
    """
    Endpoint umożliwiający upload dokumentów.
    Klient przesyła plik (PDF, DOCX lub TXT) wraz z tytułem.
    W nagłówku musi być X-API-KEY.
    """

    def post(self, request):
        # Weryfikacja klucza API
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return Response({"error": "Brak klucza API"}, status=status.HTTP_403_FORBIDDEN)

        tenant = Tenant.objects.filter(api_key=api_key).first()
        if not tenant:
            return Response({"error": "Niepoprawny klucz API"}, status=status.HTTP_403_FORBIDDEN)

        # Walidacja danych za pomocą serializera
        serializer = DocumentSerializer(data=request.data)
        if serializer.is_valid():
            # Zapisz dokument przypisując tenant
            document = serializer.save(tenant=tenant)

            # Pobierz pełną ścieżkę do zapisanego pliku
            file_path = document.file.path

            # Wyodrębnij tekst z pliku (PDF, DOCX, TXT) i zapisz do pola content
            extracted_text = extract_text(file_path)
            document.content = extracted_text
            document.save()

            # Zwróć dane dokumentu (zaktualizowane o pole content)
            return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
