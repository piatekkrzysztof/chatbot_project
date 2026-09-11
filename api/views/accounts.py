import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts import dwuskladnikowe
from accounts.models import InvitationToken, Subscription
from accounts.plans import OKRES_PROBNY_DNI, PLAN_PROBNY, message_limit_for
from accounts.registration import lock_invitation_team
from accounts.signup import RECEIPT, request_email
from accounts.utils.email import send_invitation_email
from api.mfa_throttles import MfaThrottle
from api.permissions import IsOwner
from api.registration_throttles import (
    InvitationAcceptThrottle,
    InvitationPreviewThrottle,
    RegistrationThrottle,
)
from api.schemas import (
    AcceptInvitationRequestSerializer,
    ErrorSerializer,
    InvitationPreviewSerializer,
    MeSerializer,
    MessageSerializer,
    RegistrationReceiptSerializer,
)
from api.serializers import (
    AcceptInvitationSerializer,
    CustomTokenObtainPairSerializer,
    InvitationCreateSerializer,
    InvitationReadSerializer,
    RegistrationStartSerializer,
    UserSerializer,
)
from api.throttles import LimitLogowaniaIP, LimitLogowaniaKonto
from api.utils.ciasteczka import (
    odczytaj_token_odswiezania,
    ustaw_ciasteczko_odswiezania,
    usun_ciasteczko_odswiezania,
)
from api.utils.mixins import TenantQuerysetMixin

logger = logging.getLogger(__name__)


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
    request=RegistrationStartSerializer,
    responses={202: RegistrationReceiptSerializer, 400: ErrorSerializer},
)
class ClientRegisterView(APIView):
    authentication_classes = ()
    permission_classes = ()
    throttle_classes = [RegistrationThrottle]

    def post(self, request):
        serializer = RegistrationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        payload.pop("password", None)
        request_email(payload["email"], payload)
        response = Response({"detail": RECEIPT, "verification_required": True}, status=202)
        response["Cache-Control"] = "no-store"
        return response


class BiletIKodSerializer(serializers.Serializer):
    """Bilet z pierwszego kroku i kod z aplikacji albo kod zapasowy."""

    bilet = serializers.CharField(max_length=1024)
    kod = serializers.CharField(max_length=64)


def odpowiedz_z_sesja(dane):
    """
    Odpowiedz z tokenami: dostepu w tresci, odswiezania w ciasteczku.

    Funkcja modulu, nie metoda widoku: korzystaja z niej dwa rozne kroki
    logowania i nie potrzebuje niczego z instancji. Jako metoda musialaby byc
    wolana z obcej klasy, co czyta sie jak pomylka.
    """
    odpowiedz = Response(dict(dane), status=status.HTTP_200_OK)
    odpowiedz["Cache-Control"] = "no-store"

    refresh = odpowiedz.data.get("refresh")
    if refresh:
        ustaw_ciasteczko_odswiezania(odpowiedz, refresh)
        if not settings.ZWRACAJ_REFRESH_W_TRESCI:
            # Token zostawiony w tresci laduje w localStorage, czyli dokladnie
            # tam, skad ta przebudowa go zabiera.
            del odpowiedz.data["refresh"]

    return odpowiedz


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
    # Domyslne throttle'e tego projektu opieraja sie na request.tenant albo
    # request.subscription, a tu jeszcze zadnego nie ma - wiec nie obowiazywaly
    # i hasla mozna bylo zgadywac bez ograniczen. Podajemy je wprost.
    throttle_classes = [LimitLogowaniaIP, LimitLogowaniaKonto]

    @transaction.atomic
    def post(self, zadanie, *args, **kwargs):
        # Walidacja rozpisana zamiast super().post(), bo przy wlaczonym drugim
        # skladniku tokeny NIE moga powstac w tym kroku - a super() zwraca je
        # od razu i nie daje dostepu do uzytkownika, zeby to sprawdzic.
        serializer = self.get_serializer(data=zadanie.data)
        serializer.is_valid(raise_exception=True)
        uzytkownik = serializer.user

        if dwuskladnikowe.ma_wlaczony_drugi_skladnik(uzytkownik):
            # Haslo bylo poprawne, ale sesja jeszcze nie powstaje. Bilet niesie
            # identyfikator jednorazowego wyzwania i nie otwiera niczego w API.
            response = Response(
                {
                    "wymaga_drugiego_skladnika": True,
                    "bilet": dwuskladnikowe.wystaw_bilet(uzytkownik),
                },
                status=status.HTTP_200_OK,
            )
            response["Cache-Control"] = "no-store"
            return response

        return odpowiedz_z_sesja(serializer.validated_data)


@extend_schema(
    tags=["Konto"],
    summary="Drugi krok logowania",
    description="Wymienia bilet z pierwszego kroku i kod na sesje.",
    request=BiletIKodSerializer,
    responses={200: OpenApiTypes.OBJECT},
)
class LogowanieDrugiSkladnikView(APIView):
    """
    Drugi krok logowania: bilet plus kod z aplikacji albo kod zapasowy.

    Osobna koncowka, a nie dodatkowe pole w logowaniu, bo pierwszy krok musi
    dzialac tak samo dla wszystkich - inaczej roznica w odpowiedzi zdradzalaby,
    ktore konta maja wlaczony drugi skladnik, czyli ktore warto atakowac inaczej.
    """

    authentication_classes = ()
    permission_classes = []
    # Wspólne liczniki IP/global, dodatkowo konto i budżet samego biletu.
    throttle_classes = [MfaThrottle]

    @transaction.atomic
    def post(self, zadanie):
        serializer = BiletIKodSerializer(data=zadanie.data)
        serializer.is_valid(raise_exception=True)
        uzytkownik, result = dwuskladnikowe.zakoncz_logowanie(**serializer.validated_data)
        if not uzytkownik:
            return Response(
                {
                    "error": "Kod nie pasuje."
                    if result == 400
                    else "Bilet wygasl albo jest nieprawidlowy. Zaloguj sie ponownie."
                },
                status=result,
            )

        odswiezenie = RefreshToken.for_user(uzytkownik)
        return odpowiedz_z_sesja(
            {"refresh": str(odswiezenie), "access": str(odswiezenie.access_token)}
        )


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
    # Koncowka nieuwierzytelniona, ktora wykonuje prace kryptograficzna przy
    # kazdym wywolaniu - bez limitu jest darmowym obciazeniem dla kazdego.
    throttle_classes = [LimitLogowaniaIP]

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
    throttle_classes = [InvitationAcceptThrottle]

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
    throttle_classes = [InvitationPreviewThrottle]

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

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        lock_invitation_team(request.user)
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        return InvitationToken.objects.filter(tenant=self.request.user.tenant)
