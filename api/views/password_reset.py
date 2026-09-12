from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response

from accounts.password_reset import RECEIPT, confirm_reset, reset_user
from accounts.tasks import send_password_reset
from api.password_throttles import (
    PasswordConfirmThrottle,
    PasswordRequestThrottle,
    RecoveryUnavailable,
    allow_email,
)
from api.schemas import ErrorSerializer
from api.session_security import SessionBoundaryMixin
from api.views.activation import DetailSerializer, EmailSerializer, PublicActivationView


class ResetTokenSerializer(serializers.Serializer):
    uid = serializers.RegexField(r"^[A-Za-z0-9_-]{1,32}$", max_length=32)
    token = serializers.RegexField(r"^[a-z0-9]{1,13}-[a-f0-9]{32}$", max_length=46)


class ResetPasswordSerializer(ResetTokenSerializer):
    password = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)


class PasswordResetRequestView(SessionBoundaryMixin, PublicActivationView):
    throttle_classes = [PasswordRequestThrottle]

    @extend_schema(
        tags=["Konto"],
        request=EmailSerializer,
        responses={
            202: DetailSerializer,
            400: ErrorSerializer,
            403: ErrorSerializer,
            429: ErrorSerializer,
            503: ErrorSerializer,
        },
    )
    def post(self, request):
        data = EmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"]
        if not settings.DEBUG and getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            raise RecoveryUnavailable()
        if allow_email(email):
            try:
                # Always enqueue, before any account lookup. SMTP and existence
                # checks happen only on the worker, for uniform public responses.
                send_password_reset.apply_async(args=[email], argsrepr="(<redacted>,)", expires=300)
            except Exception:
                raise RecoveryUnavailable() from None
        return Response({"detail": RECEIPT}, status=202)


class PasswordResetPreviewView(SessionBoundaryMixin, PublicActivationView):
    throttle_classes = [PasswordConfirmThrottle]

    @extend_schema(
        tags=["Konto"],
        request=ResetTokenSerializer,
        responses={
            200: DetailSerializer,
            400: ErrorSerializer,
            403: ErrorSerializer,
            429: ErrorSerializer,
            503: ErrorSerializer,
        },
    )
    def post(self, request):
        data = ResetTokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        reset_user(**data.validated_data)
        return Response({"detail": "Link jest poprawny. Ustaw nowe hasło."})


class PasswordResetConfirmView(SessionBoundaryMixin, PublicActivationView):
    throttle_classes = [PasswordConfirmThrottle]

    @extend_schema(
        tags=["Konto"],
        request=ResetPasswordSerializer,
        responses={
            200: DetailSerializer,
            400: ErrorSerializer,
            403: ErrorSerializer,
            429: ErrorSerializer,
            503: ErrorSerializer,
        },
    )
    def post(self, request):
        data = ResetPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        confirm_reset(**data.validated_data)
        return Response({"detail": "Hasło zmienione. Zaloguj się ponownie."})
