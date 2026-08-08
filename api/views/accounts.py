from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from accounts.utils.email import send_invitation_email
from accounts.models import InvitationToken
from api.serializers import RegisterSerializer, UserSerializer, AcceptInvitationSerializer

from rest_framework_simplejwt.views import TokenObtainPairView
from api.serializers import CustomTokenObtainPairSerializer

import logging

from rest_framework import generics, permissions
from api.serializers import InvitationCreateSerializer, InvitationReadSerializer

logger = logging.getLogger(__name__)
from rest_framework.exceptions import PermissionDenied
from api.utils.mixins import TenantQuerysetMixin
from rest_framework.generics import ListAPIView
from api.permissions import *
from api.utils.stripe import create_checkout_session
from drf_spectacular.utils import extend_schema

from api.schemas import (
    AcceptInvitationRequestSerializer, ErrorSerializer,
    InvitationPreviewSerializer, MeSerializer, MessageSerializer,
)


@extend_schema(
    tags=["Konto"],
    summary="Rejestracja nowej firmy",
    request=RegisterSerializer,
    responses={201: MessageSerializer, 400: ErrorSerializer},
)
class ClientRegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()

        tenant = result["tenant"]
        use_trial = result["use_trial"]

        if use_trial:
            return Response(
                {"detail": "Tenant zarejestrowany w trybie trial."},
                status=status.HTTP_201_CREATED,
            )
        else:
            checkout_url = create_checkout_session(tenant)
            return Response(
                {"checkout_url": checkout_url},
                status=status.HTTP_201_CREATED,
            )


@extend_schema(
    tags=["Konto"],
    summary="Logowanie",
    description=(
        "W polu `username` można podać zarówno nazwę użytkownika, jak i adres e-mail."
    ),
)
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = []


@extend_schema(
    tags=["Konto"],
    summary="Dane zalogowanego użytkownika",
    description="Zawiera klucz API firmy, potrzebny do osadzenia widgetu.",
    responses={200: MeSerializer},
)
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        data = UserSerializer(user).data
        data["tenant_api_key"] = str(user.tenant.api_key)
        data["tenant_name"] = user.tenant.name
        return Response(data)


@extend_schema(
    tags=["Panel — zespół"],
    summary="Zaproś osobę do zespołu",
    description=(
        "Tworzy zaproszenie i próbuje wysłać e-mail. Pole `email_sent` mówi, czy "
        "wysyłka się powiodła — link z `accept_url` działa niezależnie od niej."
    ),
    request=InvitationCreateSerializer,
    responses={201: InvitationReadSerializer},
)
class CreateInvitationView(generics.CreateAPIView):
    serializer_class = InvitationCreateSerializer
    permission_classes = [IsOwner]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()

        # Nieudana wysyłka nie może przekreślać zaproszenia: token jest już
        # zapisany, a panel i tak pokazuje link do skopiowania. Wcześniej błąd
        # SMTP kończył się pięćsetką mimo poprawnie utworzonego zaproszenia.
        try:
            send_invitation_email(invitation)
            email_sent = True
        except Exception:
            logger.exception(
                "Nie udało się wysłać zaproszenia na %s", invitation.email
            )
            email_sent = False

        data = InvitationReadSerializer(invitation).data
        data["email_sent"] = email_sent
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Konto"],
    summary="Przyjmij zaproszenie i załóż konto",
    description="Dostępne bez uwierzytelnienia — zapraszany nie ma jeszcze konta.",
    request=AcceptInvitationRequestSerializer,
    responses={201: MessageSerializer, 400: ErrorSerializer},
)
class AcceptInvitationView(APIView):
    # Zapraszany jeszcze nie ma konta, więc nie może być uwierzytelniony
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User registered successfully."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Konto"],
    summary="Sprawdź ważność zaproszenia",
    description="Wołane przez stronę rejestracji, zanim pokaże formularz.",
    responses={200: InvitationPreviewSerializer, 404: ErrorSerializer},
)
class InvitationPreviewView(APIView):
    """
    Czy zaproszenie jest jeszcze ważne — sprawdzane przez stronę rejestracji,
    zanim pokaże formularz. Bez tego zapraszany wypełnia dane, żeby dopiero
    przy zapisie dowiedzieć się, że link wygasł.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, token):
        invitation = InvitationToken.objects.filter(token=token).first()
        if invitation is None:
            return Response(
                {"detail": "Nieprawidłowy link zaproszenia."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            "company": invitation.tenant.name,
            "email": invitation.email,
            "role": invitation.role,
            "is_valid": invitation.is_valid(),
            "expires_at": invitation.expires_at,
        })


@extend_schema(tags=["Panel — zespół"], summary="Lista zaproszeń")
class InvitationListView(TenantQuerysetMixin, ListAPIView):
    permission_classes = [IsOwner]
    serializer_class = InvitationReadSerializer
    queryset = InvitationToken.objects.all().order_by("-created_at")


@extend_schema(tags=["Panel — zespół"], summary="Cofnij zaproszenie")
class InvitationRevokeView(generics.DestroyAPIView):
    """Cofnięcie zaproszenia — link przestaje działać od razu."""
    permission_classes = [IsOwner]
    serializer_class = InvitationReadSerializer

    def get_queryset(self):
        return InvitationToken.objects.filter(tenant=self.request.user.tenant)
