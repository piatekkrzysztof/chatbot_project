"""Serialize refresh consumption on the account row (also used by login/MFA)."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import UntypedToken


class RefreshAlreadyUsed(TokenError):
    pass


class AtomicTokenRefreshSerializer(TokenRefreshSerializer):
    @transaction.atomic
    def validate(self, attrs):
        value = attrs["refresh"]
        if not isinstance(value, str) or len(value) > 8192:
            raise TokenError("Invalid refresh")
        # Verify signature and expiry before trusting the account ID. Blacklist
        # verification happens again UNDER the lock, before any token is issued.
        token = UntypedToken(value)
        if token.get(api_settings.TOKEN_TYPE_CLAIM) != "refresh":
            raise TokenError("Invalid token type")
        try:
            user = (
                get_user_model()
                .objects.select_for_update()
                .get(**{api_settings.USER_ID_FIELD: token[api_settings.USER_ID_CLAIM]})
            )
        except (get_user_model().DoesNotExist, ValidationError, ValueError, TypeError, KeyError):
            raise TokenError("Account unavailable") from None
        if not api_settings.USER_AUTHENTICATION_RULE(user):
            raise TokenError("Account unavailable")
        jti = token.get(api_settings.JTI_CLAIM)
        if not isinstance(jti, str) or not jti:
            raise TokenError("Missing token ID")
        if BlacklistedToken.objects.filter(token__jti=jti).exists():
            raise RefreshAlreadyUsed("Refresh already consumed")
        return super().validate(attrs)
