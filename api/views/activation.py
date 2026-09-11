from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.registration import normalized_email
from accounts.signup import RECEIPT, request_email, valid_pending
from api.registration_throttles import InvitationAcceptThrottle, InvitationPreviewThrottle
from api.serializers import RegisterSerializer
from api.views.accounts import zalozenie_okresu_probnego


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=150)

    def validate_email(self, value):
        return normalized_email(value)


class TokenSerializer(serializers.Serializer):
    token = serializers.RegexField(r"^[A-Za-z0-9_-]{43}$", max_length=43, trim_whitespace=False)


class ActivationSerializer(TokenSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=1024)


class ResendThrottle(InvitationAcceptThrottle):
    scope = "activation-resend"
    ip_limit = 10
    global_limit = 30


class ActivationThrottle(InvitationAcceptThrottle):
    scope = "activation-confirm"


class PreviewThrottle(InvitationPreviewThrottle):
    scope = "activation-preview"


class PublicActivationView(APIView):
    authentication_classes = ()
    permission_classes = ()

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class ResendRegistrationView(PublicActivationView):
    throttle_classes = [ResendThrottle]

    @extend_schema(request=EmailSerializer, responses={202: None})
    def post(self, request):
        data = EmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        request_email(data.validated_data["email"])
        return Response({"detail": RECEIPT}, status=202)


class RegistrationPreviewView(PublicActivationView):
    throttle_classes = [PreviewThrottle]

    @extend_schema(request=TokenSerializer)
    def post(self, request):
        data = TokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        pending = valid_pending(data.validated_data["token"])
        return Response(
            {
                "email": pending.email,
                "company_name": pending.payload["company_name"],
            }
        )


class ActivateRegistrationView(PublicActivationView):
    throttle_classes = [ActivationThrottle]

    @extend_schema(request=ActivationSerializer)
    def post(self, request):
        data = ActivationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            pending = valid_pending(data.validated_data["token"], lock=True)
            registration = RegisterSerializer(
                data={**pending.payload, "password": data.validated_data["password"]}
            )
            registration.is_valid(raise_exception=True)
            result = registration.save()
            if result["use_trial"]:
                zalozenie_okresu_probnego(result["tenant"])
            pending.used_at = timezone.now()
            pending.payload = {}
            # Erase the consumed hash; this is not a configured password.
            pending.token_digest = ""  # nosec B105
            pending.save(update_fields=["used_at", "payload", "token_digest"])
        # Checkout requires a logged-in owner; activation cannot charge a customer.
        return Response(
            {
                "detail": "Adres potwierdzony. Konto jest gotowe do logowania.",
                "use_trial": result["use_trial"],
                "plan": result["plan"],
            },
            status=201,
        )
