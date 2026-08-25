import json

from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import BrandingMode, Tenant, WidgetDomain
from accounts.domains import limit_domen, zarejestruj_domene
from accounts.plans import allows_hiding_branding, allows_white_label, get_plan
from api.throttles import APIKeyRateThrottle, VisitorRateThrottle
from uuid import UUID
from rest_framework.exceptions import PermissionDenied, ValidationError
from chat.models import FAQ, Conversation
from chat.privacy import visitor_identifier
from api.serializers import PublicFAQSerializer, ChatRequestSerializer, WidgetDomainSerializer
from api.utils.chat_engine import process_chat_message, split_billing, stream_chat_message
from api.permissions import IsOwnerOrEmployee, IsOwnerOrEmployeeOrTenantReadOnly
from django.http import StreamingHttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema

from api.schemas import (
    ErrorSerializer, PublicChatResponseSerializer, WidgetBrandingSerializer,
)



def _wlaczone(wartosc):
    """
    Wartość logiczna z formularza albo z JSON-a.

    Panel wysyła ustawienia jako multipart, bo w tym samym żądaniu lecą logo
    i awatar — a wtedy `true` zamienia się w napis "true". Django odrzuca taki
    napis wyjątkiem (uznaje wyłącznie "True", "1"), więc przypisanie go wprost
    do pola logicznego kończyło zapis błędem 500 zamiast zapisać ustawienie.
    """
    if isinstance(wartosc, str):
        return wartosc.strip().lower() in ("true", "1", "on", "yes")
    return bool(wartosc)


def branding_dla_panelu(tenant, request):
    """
    To samo co serialize_widget_branding plus ustawienia, które widzi wyłącznie
    właściciel.

    Rozdzielone, bo serialize_widget_branding zasila też publiczny endpoint
    czytany przez sam widget — z samym kluczem API, bez logowania. Wszystko,
    co tam trafi, jest odczytywalne przez każdego, kto podejrzy kod strony
    klienta. Preferencje powiadomień właściciela nie mają tam czego szukać.
    """
    dane = serialize_widget_branding(tenant, request)
    dane["powiadom_o_rozmowie"] = tenant.powiadom_o_rozmowie
    dane["raport_tygodniowy"] = tenant.raport_tygodniowy
    return dane


def serialize_widget_branding(tenant, request):
    # Wersja językowa strony klienta, przekazana przez embed.js z atrybutu
    # <html lang>. Zaczepkę wybieramy po stronie serwera, bo widget i tak nie
    # ma po czym rozpoznać języka — odwiedzający jeszcze nic nie napisał.
    lang_strony = request.GET.get("lang", "")
    return {
        "widget_position": tenant.widget_position,
        "widget_color": tenant.widget_color,
        "widget_title": tenant.widget_title,
        "branding_mode": tenant.branding_mode,
        "widget_footer_text": tenant.widget_footer_text,
        "widget_logo": request.build_absolute_uri(tenant.widget_logo.url) if tenant.widget_logo else None,
        "widget_avatar": request.build_absolute_uri(tenant.widget_avatar.url) if tenant.widget_avatar else None,
        # RODO wymaga poinformowania odwiedzającego o przetwarzaniu jego danych
        # w momencie ich zbierania — czyli w oknie czatu, nie tylko w regulaminie.
        "privacy_policy_url": tenant.privacy_policy_url or "",
        "widget_welcome_message": tenant.widget_welcome_message or "",
        "widget_suggested_questions": tenant.suggested_questions(),
        "widget_languages": tenant.languages(),
        "widget_language_mode": tenant.widget_language_mode,
        "widget_default_language": tenant.default_language(),
        "widget_hide_branding": tenant.widget_hide_branding,
        "widget_proactive_enabled": tenant.widget_proactive_enabled,
        "widget_proactive_delay_seconds": tenant.widget_proactive_delay_seconds,
        "widget_proactive_text": tenant.proactive_text_for(lang_strony),
        # Panel potrzebuje kompletu, żeby dało się edytować wszystkie wersje
        "widget_proactive_texts": tenant.proactive_texts(),
    }


@extend_schema(
    tags=["Widget"],
    summary="Wygląd widgetu",
    description=(
        "Branding okna czatu dla podanego klucza API. Wołane przez widget przy "
        "starcie, zanim odwiedzający cokolwiek napisze."
    ),
    responses={
        200: WidgetBrandingSerializer,
        403: OpenApiResponse(description="Brak lub nieprawidłowy klucz API."),
    },
)
class WidgetSettingsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        if not getattr(request, "tenant", None):
            return Response({"error": "Brak poprawnego klucza API"}, status=403)

        # To jedyne zapytanie widgetu niosące prawdziwy adres witryny klienta:
        # samo okno czatu działa w ramce na naszej domenie, więc jego Origin
        # wskazywałby nas, nie klienta. Stąd rejestr domen siedzi właśnie tutaj.
        zarejestruj_domene(request.tenant, request.headers.get("Origin"))

        return Response(serialize_widget_branding(request.tenant, request), status=status.HTTP_200_OK)


@extend_schema(
    tags=["Widget"],
    summary="FAQ firmy",
    description="Lista pytań i odpowiedzi skonfigurowanych przez firmę.",
    responses={200: PublicFAQSerializer(many=True)},
)
class PublicFAQView(APIView):
    authentication_classes = []  # brak JWT
    permission_classes = []  # walidacja przez API key (X-API-KEY), wykonana w TenantMiddleware

    def get(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        faqs = FAQ.objects.filter(tenant=request.tenant).order_by("id")
        serializer = PublicFAQSerializer(faqs, many=True)
        return Response(serializer.data)


@extend_schema(
    tags=["Widget"],
    summary="Zadaj pytanie botowi",
    description=(
        "Wysyła wiadomość odwiedzającego i zwraca całą odpowiedź naraz. "
        "Rozmowę wiąże `conversation_session_id` — ten sam identyfikator w kolejnych "
        "żądaniach daje botowi pamięć kontekstu. Zużywa jedną wiadomość z limitu planu."
    ),
    request=ChatRequestSerializer,
    responses={
        200: PublicChatResponseSerializer,
        403: OpenApiResponse(response=ErrorSerializer, description="Nieprawidłowy klucz API."),
        429: OpenApiResponse(description="Wyczerpany limit wiadomości w planie."),
    },
)
class PublicChatView(APIView):
    """
    Publiczny endpoint czatu dla osadzalnego widgetu — autoryzacja przez
    X-API-Key (request.tenant/request.subscription ustawiane przez middleware),
    bez logowania JWT. Odpowiednik ChatWithGPTView dla anonimowych odwiedzających
    stronę klienta.
    """
    authentication_classes = []
    permission_classes = []
    # Limit per firma chroni nas, limit per odwiedzający chroni klienta przed
    # jednym rozmówcą wyczerpującym mu cały miesięczny pakiet
    throttle_classes = [VisitorRateThrottle]

    def post(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        subscription = getattr(request, "subscription", None)

        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = request.tenant

        conversation, _ = Conversation.objects.get_or_create(
            session_id=data["conversation_session_id"],
            tenant=tenant,
            defaults={
                "tenant": tenant,
                "user_identifier": visitor_identifier(request),
                "source": "widget",
            }
        )

        result = process_chat_message(tenant, conversation, data["message"].strip())

        # Awaria modelu nie zjada limitu, za który klient zapłacił
        payload, billable = split_billing(result)
        if billable and subscription:
            subscription.increment_usage()

        return Response(payload)


@extend_schema(
    tags=["Widget"],
    summary="Zadaj pytanie botowi (strumieniowo)",
    description=(
        "To samo co `/widget/chat/`, ale odpowiedź leci token po tokenie jako "
        "Server-Sent Events (`text/event-stream`). Każde zdarzenie to JSON: "
        "`{\"type\": \"delta\", \"content\": \"...\"}` w trakcie, a na koniec "
        "`{\"type\": \"done\", \"source\": ..., \"tokens\": ..., \"sources\": [...]}`."
    ),
    request=ChatRequestSerializer,
    responses={
        (200, "text/event-stream"): OpenApiResponse(description="Strumień zdarzeń SSE."),
        403: OpenApiResponse(response=ErrorSerializer, description="Nieprawidłowy klucz API."),
        429: OpenApiResponse(description="Wyczerpany limit wiadomości w planie."),
    },
)
class PublicChatStreamView(APIView):
    """
    Strumieniowa wersja PublicChatView — odpowiedź leci token po tokenie (SSE),
    dzięki czemu użytkownik widzi ją od razu zamiast czekać na całość.
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = [VisitorRateThrottle]

    def post(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = request.tenant

        conversation, _ = Conversation.objects.get_or_create(
            session_id=data["conversation_session_id"],
            tenant=tenant,
            defaults={
                "tenant": tenant,
                "user_identifier": visitor_identifier(request),
                "source": "widget",
            }
        )

        # Naliczamy dopiero, gdy odwiedzający realnie dostanie treść od modelu.
        # Wcześniej limit schodził z góry, więc awaria po naszej stronie
        # kosztowała klienta wiadomość. Samego limitu to nie osłabia — sprawdza
        # go SubscriptionMiddleware, zanim ten widok w ogóle się wykona.
        subscription = getattr(request, "subscription", None)

        response = StreamingHttpResponse(
            stream_chat_message(
                tenant, conversation, data["message"].strip(),
                on_billable=subscription.increment_usage if subscription else None,
            ),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # wyłącza buforowanie na nginx/proxy
        return response


@extend_schema(
    tags=["Panel — widget"],
    summary="Branding widgetu (odczyt i zapis)",
    request=WidgetBrandingSerializer,
    responses={200: WidgetBrandingSerializer},
)
class TenantWidgetSettingsView(APIView):
    """
    Uwierzytelniony (JWT) branding widgetu dla panelu klienta —
    odpowiednik WidgetSettingsAPIView, ale do odczytu/zapisu przez właściciela,
    nie do publicznego odczytu przez sam widget.
    """
    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]

    def get(self, request):
        return Response(branding_dla_panelu(request.user.tenant, request))

    def patch(self, request):
        tenant = request.user.tenant

        # Biała etykieta to główny wyróżnik płatnych planów. Bez tej blokady
        # klient Basic ustawiał sobie własny branding zwykłym żądaniem PATCH,
        # bo ograniczenie istniało wyłącznie w cenniku.
        subscription = getattr(tenant, "subscription", None)
        plan_code = subscription.plan_type if subscription else None
        plan = get_plan(plan_code)
        nazwa_planu = plan.name if plan else plan_code

        if request.data.get("branding_mode") == BrandingMode.WHITE_LABEL:
            if not allows_white_label(plan_code):
                raise PermissionDenied(
                    f"Własny branding nie jest dostępny w planie "
                    f"{nazwa_planu}. Przejdź na wyższy plan."
                )

        # Ukrycie stopki to niższy próg niż własna marka i osobna pozycja
        # w cenniku — bez tej bramki klient planu Start wyłączyłby ją
        # zwykłym żądaniem PATCH, tak jak wcześniej było z białą etykietą.
        if _wlaczone(request.data.get("widget_hide_branding")):
            if not allows_hiding_branding(plan_code):
                raise PermissionDenied(
                    f"Ukrycie stopki nie jest dostępne w planie "
                    f"{nazwa_planu}. Przejdź na wyższy plan."
                )

        text_fields = (
            "widget_position", "widget_color", "widget_title", "branding_mode",
            "widget_footer_text", "widget_welcome_message", "widget_suggested_questions",
            "widget_languages", "widget_language_mode", "widget_default_language",
            "widget_proactive_delay_seconds",
        )
        # Osobno, bo z formularza przychodzą jako napisy "true"/"false"
        bool_fields = ("widget_proactive_enabled", "widget_hide_branding",
                       "powiadom_o_rozmowie", "raport_tygodniowy")
        changed_fields = []

        for field in text_fields:
            if field in request.data:
                setattr(tenant, field, request.data[field])
                changed_fields.append(field)

        for field in bool_fields:
            if field in request.data:
                setattr(tenant, field, _wlaczone(request.data[field]))
                changed_fields.append(field)

        # Teksty zaczepki przychodzą jako słownik (JSON) albo jako string
        # z formularza multipart — panel wysyła branding razem z plikami.
        if "widget_proactive_texts" in request.data:
            surowe = request.data["widget_proactive_texts"]
            if isinstance(surowe, str):
                try:
                    surowe = json.loads(surowe)
                except ValueError:
                    raise ValidationError(
                        {"widget_proactive_texts": "Nieprawidłowy JSON."}
                    )
            if not isinstance(surowe, dict):
                raise ValidationError(
                    {"widget_proactive_texts": "Oczekiwano obiektu kod języka → tekst."}
                )
            tenant.widget_proactive_texts = surowe
            changed_fields.append("widget_proactive_texts")

        for file_field in ("widget_logo", "widget_avatar"):
            if file_field in request.FILES:
                setattr(tenant, file_field, request.FILES[file_field])
                changed_fields.append(file_field)

        if changed_fields:
            tenant.save(update_fields=changed_fields)

        return Response(branding_dla_panelu(tenant, request))


@extend_schema(
    tags=["Panel — widget"],
    summary="Witryny, na których działa widget",
    description=(
        "Lista witryn wykrytych po nagłówku Origin, wraz z limitem planu. "
        "Usunięcie zwalnia miejsce — witryna zarejestruje się ponownie, gdy "
        "widget znów z niej zapyta."
    ),
)
class WidgetDomainViewSet(viewsets.ModelViewSet):
    """
    Podgląd i usuwanie witryn. Bez dodawania ręcznego: rejestrują się same
    przy pierwszym zapytaniu, a wpis dodany z palca i tak nie dałby dostępu
    witrynie, która o widget nie prosi.
    """
    serializer_class = WidgetDomainSerializer
    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]
    # Bez tego generator schematu nie potrafi wywnioskować typu identyfikatora
    # w ścieżce, bo queryset zależy od zalogowanego użytkownika
    queryset = WidgetDomain.objects.none()
    http_method_names = ["get", "delete", "head", "options"]

    def get_queryset(self):
        return WidgetDomain.objects.filter(tenant=self.request.user.tenant)

    def list(self, request, *args, **kwargs):
        tenant = request.user.tenant
        domeny = self.get_queryset()
        return Response({
            "domains": WidgetDomainSerializer(domeny, many=True).data,
            "limit": limit_domen(tenant),
            "used": domeny.count(),
        })
