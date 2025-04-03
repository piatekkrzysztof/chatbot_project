from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import Tenant
from documents.models import Document
from api.serializers import DocumentSerializer


class DocumentUploadView(APIView):
    """
    Endpoint umożliwiający upload dokumentu.
    Klient wysyła plik wraz z tytułem. W nagłówku musi być 'X-API-KEY'.
    """

    def post(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return Response({"error": "Brak klucza API"}, status=status.HTTP_403_FORBIDDEN)

        tenant = Tenant.objects.filter(api_key=api_key).first()
        if not tenant:
            return Response({"error": "Nieprawidłowy klucz API"}, status=status.HTTP_403_FORBIDDEN)

        serializer = DocumentSerializer(data=request.data)
        if serializer.is_valid():
            document = serializer.save(tenant=tenant)
            # Tu można dodać logikę przetwarzania pliku (np. konwersja PDF -> tekst)
            # Przykład: document.content = extract_text(document.file.path)
            # document.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
