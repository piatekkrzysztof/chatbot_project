from rest_framework import viewsets, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from api.serializers import DocumentSerializer
from documents.models import Document
from documents.utils.file_to_text import extract_text
from documents.utils.embeddings import add_document_to_embeddings


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        document = serializer.save()

        # wyciągamy tekst z dokumentu
        text = extract_text(document.file.path)

        # Tworzymy embeddings dla dokumentu
        add_document_to_embeddings(document.tenant, text, document.id)
