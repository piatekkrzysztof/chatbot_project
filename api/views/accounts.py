from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from accounts.utils.email import send_invitation_email
from accounts.models import InvitationToken
from api.serializers import RegisterSerializer, UserSerializer, AcceptInvitationSerializer

from django.conf import settings
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from api.serializers import CustomTokenObtainPairSerializer
from api.utils.ciasteczka import (
    odczytaj_token_odswiezania,
    ustaw_ciasteczko_odswiezania,
    usun_ciasteczko_odswiezania,
)

import logging

from rest_framework import generics, permissions
from api.serializers import InvitationCreateSerializer, InvitationReadSerializer

logger = logging.getLogger(__name__)
from rest_framework.exceptions import PermissionDenied
from api.utils.mixins import TenantQuerysetMixin
from rest_framework.generics import ListAPIView
from api.permissions import *
from datetime import timedelta

from django.utils import timezone

from accounts.models import Subscription
from accounts.plans import OKRES_PROBNY_DNI, PLAN_PROBNY, message_limit_for
from api.views.stripe import create_checkout_session
from drf_spectacular.utils import extend_schema

from api.schemas import (
    AcceptInvitationRequestSerializer,
    ErrorSerializer,
    InvitationPreviewSerializer,
    MeSerializer,
    MessageSerializer,
)


def zalozenie_okresu_probnego(tenant):
    """
    Subskrypcja próbna dla świeżo założonego konta.

    Limity z najniższego planu: klient ma poznać produkt, nie dostać go za
    darmo. Data końca zamyka okres sama, bez zadania w tle — wygasłą
    subskrypcję odrzuca to samo sprawdzenie dat co w płatnych planach.
    """
    dzisiaj = timezone.now().date()
    return Subscription.objects.create(
        tenant=tenant,
        plan_type=PLAN_PROBNY,
        start_date=dzisiaj,
        end_date=dzisiaj + timedelta(days=OKRES_PROBNY_DNI),
        is_active=True,
        message_limit=message_limit_for(PLAN_PROBNY),
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
            # Subskrypcja musi powstać już teraz. SubscriptionMiddleware wymaga
            # jej dla /api/widget/chat/, więc bez tego klient skonfigurowałby
            # bota, wkleił kod na stronę i zobaczył odmowę zamiast odpowiedzi.
            zalozenie_okresu_probnego(tenant)
            return Response(
                {"detail": "Konto założone w okresie próbnym."},
                status=status.HTTP_201_CREATED,
            )
        else:
            checkout_url = create_checkout_session(
                tenant, plan_code=result["plan"], email=tenant.owner_email
            )
            return Response(
                {"checkout_url": checkout_url},
                status=status.HTTP_201_CREATED,
            )


@extend_schema(
    tags=["Konto"],
    summary="Logowanie",
    description=("W polu `username` można podać zarówno nazwę użytkownika, jak i adres e-mail."),
)
class LoginView(TokenObtainPairView):
    """
    Logowanie. Token dostepu wraca w tresci, token odswiezania w ciasteczku.

    Rozdzial jest celowy: token dostepu zyje krotko i frontend trzyma go
    w pamiecie karty, a token odswiezania -- ten, ktorym da sie odtworzyc
    sesje na dwa tygodnie -- nie jest widoczny dla zadnego skryptu.
    """

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = []

    def post(self, zadanie, *args, **kwargs):
        odpowiedz = super().post(zadanie, *args, **kwargs)

        refresh = odpowiedz.data.get("refresh")
        if refresh:
            ustaw_ciasteczko_odswiezania(odpowiedz, refresh)
            if not settings.ZWRACAJ_REFRESH_W_TRESCI:
                # Token zostawiony w tresci laduje w localStorage, czyli
                # dokladnie tam, skad ta przebudowa go zabiera.
                del odpowiedz.data["refresh"]

        return odpowiedz


@extend_schema(
    tags=["Konto"],
    summary="Odswiez token dostepu",
    description=(
        "Czyta token odswiezania z ciasteczka HttpOnly. Kazde wywolanie wydaje "
        "nowy token odswiezania i uniewaznia poprzedni."
    ),
)
class OdswiezTokenView(TokenRefreshView):
    """
    Odswiezanie oparte o ciasteczko.

    Domyslny widok simplejwt oczekuje tokenu w tresci zadania. Skoro token
    jest teraz niewidoczny dla JavaScriptu, frontend nie ma czego wyslac --
    czytamy go z ciasteczka i tam tez odsylamy nowy.
    """

    permission_classes = []

    def post(self, zadanie, *args, **kwargs):
        token = odczytaj_token_odswiezania(zadanie)
        if not token:
            # 401, nie 400: dla frontendu to ten sam przypadek co wygasla
            # sesja i ma prowadzic do ekranu logowania, a nie do komunikatu
            # o bledzie formularza.
            odpowiedz = Response(
                {"detail": "Brak tokenu odswiezania."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            # Kasujemy tez znacznik sesji. Bez tego przegladarka zostaje ze
            # sladem po sesji, ktorej juz nie ma: Next.js przepuszcza trase
            # panelu, panel odbija na logowanie, i tak w kolko.
            usun_ciasteczko_odswiezania(odpowiedz)
            return odpowiedz

        serializer = self.get_serializer(data={"refresh": token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as blad:
            odpowiedz = Response(
                {"detail": "Sesja wygasla. Zaloguj sie ponownie."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            # Token nie do uzycia -- ciasteczko tylko myli przegladarke
            # i kaze jej probowac w nieskonczonosc.
            usun_ciasteczko_odswiezania(odpowiedz)
            logger.info("Odrzucony token odswiezania: %s", blad)
            return odpowiedz

        dane = dict(serializer.validated_data)
        nowy_refresh = dane.pop("refresh", None)

        odpowiedz = Response(dane, status=status.HTTP_200_OK)
        if nowy_refresh:
            # Rotacja: poprzedni token trafil wlasnie na czarna liste,
            # wiec bez podmiany ciasteczka nastepne odswiezenie odbiloby sie.
            ustaw_ciasteczko_odswiezania(odpowiedz, nowy_refresh)
        return odpowiedz


@extend_schema(
    tags=["Konto"],
    summary="Wyloguj",
    description="Uniewaznia token odswiezania i kasuje ciasteczko.",
    # Widok nie przyjmuje ani nie zwraca tresci -- token przychodzi
    # w ciasteczku. Bez tych dwoch linii generator schematu probuje zgadnac
    # serializer, nie potrafi i zglasza blad.
    request=None,
    responses={204: None},
)
class WylogujView(APIView):
    """
    Wylogowanie, ktore naprawde konczy sesje.

    Samo skasowanie ciasteczka byloby gestem po stronie przegladarki: token
    dzialalby dalej az do konca swojego zycia, wiec kopia zdjeta wczesniej
    z tego samego urzadzenia otwieralaby panel jeszcze przez dwa tygodnie.
    Dlatego token trafia na czarna liste.
    """

    permission_classes = []

    def post(self, zadanie):
        token = odczytaj_token_odswiezania(zadanie)
        odpowiedz = Response(status=status.HTTP_204_NO_CONTENT)

        if token:
            try:
                RefreshToken(token).blacklist()
            except TokenError:
                # Token juz wygasly albo juz uniewazniony. Z punktu widzenia
                # uzytkownika wylogowanie sie udalo, wiec nie ma o czym
                # informowac -- nie ma tez czego uniewazniac.
                pass

        usun_ciasteczko_odswiezania(odpowiedz)
        return odpowiedz


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
            logger.exception("Nie udało się wysłać zaproszenia na %s", invitation.email)
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
            return Response(
                {"message": "User registered successfully."}, status=status.HTTP_201_CREATED
            )
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

        return Response(
            {
                "company": invitation.tenant.name,
                "email": invitation.email,
                "role": invitation.role,
                "is_valid": invitation.is_valid(),
                "expires_at": invitation.expires_at,
            }
        )


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
