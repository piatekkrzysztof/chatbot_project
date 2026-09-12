"""Issue, rotate and revoke a login's tokens under the same account lock."""

import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.utils import datetime_from_epoch

from accounts.sessions import LoginSession


def session_id(token):
    try:
        value = token["sid"]
        if not isinstance(value, str):
            raise ValueError
        return uuid.UUID(value)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise TokenError("Session unavailable") from None


def active_session(token, user):
    session = LoginSession.objects.filter(
        pk=session_id(token), user=user, revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).first()
    if session is None or not constant_time_compare(
        session.password_fingerprint, user.get_session_auth_hash()
    ):
        raise TokenError("Session unavailable")
    return session


def locked_user(token):
    try:
        return (
            get_user_model()
            .objects.select_for_update()
            .get(**{api_settings.USER_ID_FIELD: token[api_settings.USER_ID_CLAIM]})
        )
    except (get_user_model().DoesNotExist, ValidationError, ValueError, TypeError, KeyError):
        raise TokenError("Account unavailable") from None


def verified_refresh(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise TokenError("Invalid refresh")
    token = UntypedToken(value)
    if token.get(api_settings.TOKEN_TYPE_CLAIM) != "refresh":
        raise TokenError("Invalid token type")
    return token


class SessionRefreshToken(RefreshToken):
    @classmethod
    @transaction.atomic
    def for_user(cls, user):
        user = type(user).objects.select_for_update().get(pk=user.pk)
        if not api_settings.USER_AUTHENTICATION_RULE(user):
            raise TokenError("Account unavailable")
        token = super().for_user(user)
        session = LoginSession.objects.create(
            user=user,
            password_fingerprint=user.get_session_auth_hash(),
            expires_at=datetime_from_epoch(token["exp"]),
        )
        token["sid"] = str(session.pk)
        # for_user stores the token before our session claim has been added.
        OutstandingToken.objects.filter(jti=token[api_settings.JTI_CLAIM]).update(token=str(token))
        return token


class SessionJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        try:
            active_session(validated_token, user)
        except TokenError:
            raise AuthenticationFailed(
                "Sesja wygasła. Zaloguj się ponownie.", code="session_revoked"
            ) from None
        return user


@transaction.atomic
def revoke_session(value):
    # Verify signature/expiry but deliberately allow a rotated, blacklisted
    # ancestor: its signed sid proves ownership of the same login session.
    token = verified_refresh(value)
    user = locked_user(token)
    LoginSession.objects.filter(pk=session_id(token), user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


class RefreshAlreadyUsed(TokenError):
    pass


class AtomicTokenRefreshSerializer(TokenRefreshSerializer):
    token_class = SessionRefreshToken

    @transaction.atomic
    def validate(self, attrs):
        value = attrs["refresh"]
        # Verify signature and expiry before trusting the account ID. Blacklist
        # verification happens again UNDER the lock, before any token is issued.
        token = verified_refresh(value)
        user = locked_user(token)
        if not api_settings.USER_AUTHENTICATION_RULE(user):
            raise TokenError("Account unavailable")
        session = active_session(token, user)
        jti = token.get(api_settings.JTI_CLAIM)
        if not isinstance(jti, str) or not jti:
            raise TokenError("Missing token ID")
        if BlacklistedToken.objects.filter(token__jti=jti).exists():
            raise RefreshAlreadyUsed("Refresh already consumed")
        refresh = self.token_class(value)
        access = refresh.access_token
        expires = int(session.expires_at.timestamp())
        access["exp"] = min(access["exp"], expires)
        refresh.blacklist()
        refresh.set_jti()
        refresh.set_iat()
        # Absolute session lifetime: rotation cannot extend the original login.
        refresh["exp"] = expires
        refresh.outstand()
        return {"access": str(access), "refresh": str(refresh)}
