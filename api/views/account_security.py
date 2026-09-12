"""Self-service account security; every write rechecks the session under a user lock."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError

from accounts import dwuskladnikowe
from accounts.models import CustomUser, DrugiSkladnik
from accounts.security_notifications import record_password_change
from accounts.sessions import LoginSession
from api.mfa_throttles import MfaThrottle, account_attempt
from api.session_security import SessionBoundaryMixin
from api.session_tokens import SessionJWTAuthentication, active_session, session_id


class CredentialsSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        max_length=1024, trim_whitespace=False, write_only=True
    )
    kod = serializers.CharField(max_length=64, required=False, allow_blank=True, write_only=True)


class PasswordChangeSerializer(CredentialsSerializer):
    new_password = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)


class MutationResultSerializer(serializers.Serializer):
    detail = serializers.CharField()
    current_session_revoked = serializers.BooleanField()


class SessionSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()

    class Meta:
        model = LoginSession
        fields = ["id", "created_at", "expires_at", "current"]

    def get_current(self, session) -> bool:
        return session.pk == session_id(self.context["request"].auth)


class SessionsPagination(PageNumberPagination):
    page_size = 20

    def get_paginated_response_schema(self, schema):
        result = super().get_paginated_response_schema(schema)
        result["properties"]["mfa_enabled"] = {"type": "boolean"}
        result.setdefault("required", []).append("mfa_enabled")
        return result

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["mfa_enabled"] = dwuskladnikowe.ma_wlaczony_drugi_skladnik(self.request.user)
        return response


class SessionListThrottle(MfaThrottle):
    scope = "account-sessions-read"
    ip_limit = 60
    window = 60
    global_limit = 600


class AccountView(SessionBoundaryMixin, APIView):
    authentication_classes = [SessionJWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [MfaThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Referrer-Policy"] = "no-referrer"
        return response


@extend_schema(tags=["Konto"], summary="Własne aktywne sesje logowania")
class SessionsView(AccountView, ListAPIView):
    serializer_class = SessionSerializer
    pagination_class = SessionsPagination
    throttle_classes = [SessionListThrottle]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LoginSession.objects.none()
        return LoginSession.objects.filter(
            user=self.request.user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
            password_fingerprint=self.request.user.get_session_auth_hash(),
        ).order_by("-created_at", "-id")


def locked_account(request, data):
    try:
        user = CustomUser.objects.select_for_update().get(pk=request.user.pk, is_active=True)
        session = active_session(request.auth, user)
    except (CustomUser.DoesNotExist, TokenError):
        raise AuthenticationFailed("Sesja wygasła. Zaloguj się ponownie.") from None
    account_attempt(user)
    if not user.check_password(data["current_password"]):
        raise ValidationError({"detail": "Nieprawidłowe aktualne hasło."})
    return user, session


def confirm_factor(user, data):
    factor = DrugiSkladnik.objects.filter(uzytkownik=user, potwierdzony_od__isnull=False).first()
    if factor and not (
        dwuskladnikowe.sprawdz_kod(factor, data.get("kod", ""))
        or dwuskladnikowe.zuzyj_kod_zapasowy(user, data.get("kod", ""))
    ):
        raise ValidationError(
            {"detail": "Podaj aktualny kod MFA albo niewykorzystany kod zapasowy."}
        )


class PasswordChangeView(AccountView):
    @extend_schema(
        tags=["Konto"], request=PasswordChangeSerializer, responses={200: MutationResultSerializer}
    )
    @transaction.atomic
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user, _ = locked_account(request, data)
        if user.check_password(data["new_password"]):
            raise ValidationError({"detail": "Nowe hasło musi różnić się od aktualnego."})
        try:
            validate_password(data["new_password"], user)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": " ".join(exc.messages)}) from None
        confirm_factor(user, data)
        user.set_password(data["new_password"])
        user.save(update_fields=["password"])
        record_password_change(user)
        LoginSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        return Response(
            {"detail": "Hasło zmienione. Zaloguj się ponownie.", "current_session_revoked": True}
        )


class RevokeSessionView(AccountView):
    @extend_schema(
        tags=["Konto"], request=CredentialsSerializer, responses={200: MutationResultSerializer}
    )
    @transaction.atomic
    def post(self, request, session_uuid):
        serializer = CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, current = locked_account(request, serializer.validated_data)
        target = LoginSession.objects.filter(pk=session_uuid, user=user).first()
        if target is None:
            raise NotFound("Nie znaleziono sesji.")
        confirm_factor(user, serializer.validated_data)
        LoginSession.objects.filter(pk=target.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        return Response(
            {"detail": "Sesja zakończona.", "current_session_revoked": target.pk == current.pk}
        )


class RevokeOtherSessionsView(AccountView):
    @extend_schema(
        tags=["Konto"], request=CredentialsSerializer, responses={200: MutationResultSerializer}
    )
    @transaction.atomic
    def post(self, request):
        serializer = CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, current = locked_account(request, serializer.validated_data)
        confirm_factor(user, serializer.validated_data)
        LoginSession.objects.filter(user=user, revoked_at__isnull=True).exclude(
            pk=current.pk
        ).update(revoked_at=timezone.now())
        return Response({"detail": "Pozostałe sesje zakończone.", "current_session_revoked": False})
