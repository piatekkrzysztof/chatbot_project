"""Enforce multipart byte limits while receiving, before disk/storage writes."""

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from rest_framework.exceptions import APIException
from rest_framework.parsers import MultiPartParser

from documents.file_limits import MAX_DOCUMENT_BYTES, MAX_IMAGE_BYTES


class UploadLimitError(APIException):
    status_code = 413
    default_detail = "Plik przekracza dozwolony rozmiar."
    default_code = "upload_too_large"


class LimitedUploadHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        path = request.path if request else ""
        self.allowed = None
        self.limit = 0
        if path.rstrip("/") == "/api/documents-upload":
            self.allowed = {"file"}
            self.limit = min(settings.DOCUMENT_MAX_UPLOAD_BYTES, MAX_DOCUMENT_BYTES)
        elif path.rstrip("/") == "/api/widget-settings/mine":
            self.allowed = {"widget_logo", "widget_avatar"}
            self.limit = min(settings.BRANDING_MAX_UPLOAD_BYTES, MAX_IMAGE_BYTES)
        self.seen = set()
        self.received = 0

    def reject(self):
        self.request._upload_limit_exceeded = True
        raise StopUpload(connection_reset=True)

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if (
            self.allowed
            and content_length
            and content_length > self.limit * len(self.allowed) + 65536
        ):
            self.reject()

    def new_file(self, field_name, *args, **kwargs):
        super().new_file(field_name, *args, **kwargs)
        self.received = 0
        if self.allowed:
            if field_name not in self.allowed or field_name in self.seen:
                self.reject()
            self.seen.add(field_name)

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.allowed and self.received > self.limit:
            self.reject()
        return raw_data

    def file_complete(self, file_size):
        return None


class LimitedMultiPartParser(MultiPartParser):
    def parse(self, stream, media_type=None, parser_context=None):
        request = parser_context["request"]._request
        try:
            result = super().parse(stream, media_type, parser_context)
        except StopUpload:
            raise UploadLimitError() from None
        if getattr(request, "_upload_limit_exceeded", False):
            raise UploadLimitError()
        return result
