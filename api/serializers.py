from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts import nip as nip_pl
from accounts.models import CustomUser, DaneRozliczeniowe, Tenant, InvitationToken, WidgetDomain
from accounts.plans import PLANS, PRO
from accounts.seats import sprawdz_limit_miejsc
from chat.models import PromptLog, ChatMessage, ChatFeedback, FAQ, ContactRequest
from documents.models import Document, DocumentChunk, WebsiteSource


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "tenant",
            "is_active",
            "last_login",
        ]
        read_only_fields = ["id", "tenant", "last_login"]


class ChatRequestSerializer(serializers.Serializer):
    # Bez ograniczenia długości odwiedzający mógł wkleić dowolnie duży tekst,
    # za którego tokeny wejściowe płacimy my. Realne pytanie mieści się
    # w kilkuset znakach; limit siedzi w ustawieniach, bo zależy od kosztów.
    message = serializers.CharField(max_length=settings.MAX_WIADOMOSC_ZNAKOW)
    # Konwersację identyfikuje wyłącznie session_id — widoki nigdy nie sięgały po nic
    # innego. Wcześniejsze, wymagane `conversation_id` nie było przez nie odczytywane,
    # więc widget wysyłał tę samą wartość dwa razy, żeby przejść walidację.
    conversation_session_id = serializers.UUIDField()


class ChatResponseSerializer(serializers.Serializer):
    response = serializers.CharField()


class WidgetSettingsSerializer(serializers.Serializer):
    widget_position = serializers.CharField()
    widget_color = serializers.CharField()
    widget_title = serializers.CharField()


class RegisterSerializer(serializers.Serializer):
    """
    Rejestracja zbiera od razu to, co i tak trzeba mieć do faktury i umowy.

    Alternatywą było pytanie o dane rozliczeniowe dopiero przy pierwszej
    płatności - mniej pól przy zakładaniu konta, więcej osób kończy rejestrację.
    Wybór padł na komplet od razu, świadomie: klient, który dochodzi do
    płatności i dopiero tam dostaje drugi formularz, przerywa w gorszym miejscu,
    a my przez cały okres próbny nie wiemy nawet, z kim rozmawiamy.

    Gdyby okazało się to zbyt kosztowne w konwersji, poluzowanie jest jedną
    zmianą: `required=False` na polach adresowych i sprawdzenie kompletu przed
    utworzeniem sesji płatności.
    """

    # Osoba zakładająca konto. Do umowy i do tego, żeby wiadomości nie
    # zaczynały się od "Szanowni Państwo" w rozmowie z jedną osobą.
    imie = serializers.CharField(max_length=60)
    nazwisko = serializers.CharField(max_length=60)

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    # Nazwa widoczna w panelu i w widgecie - krótka, robocza.
    company_name = serializers.CharField(max_length=100)

    # Dane rozliczeniowe. `nazwa_do_faktury` bywa inna niż nazwa robocza:
    # w panelu "Rowerownia", na fakturze "Rowerownia Krakowska Jan Kowalski".
    nazwa_do_faktury = serializers.CharField(max_length=200, required=False, allow_blank=True)
    nip = serializers.CharField(max_length=15, required=False, allow_blank=True)
    ulica = serializers.CharField(max_length=200)
    kod_pocztowy = serializers.CharField(max_length=12)
    miasto = serializers.CharField(max_length=100)
    kraj = serializers.CharField(max_length=2, required=False, default="PL")

    use_trial = serializers.BooleanField(default=True)
    # Bez tego rejestracja kupowała zawsze ten sam plan, niezależnie od wyboru
    plan = serializers.ChoiceField(choices=list(PLANS), default=PRO)

    def validate_nip(self, value):
        """
        Suma kontrolna, nie istnienie firmy.

        NIP z literówką wygląda jak NIP i wychodzi dopiero na fakturze - czyli
        u księgowej klienta, kilka tygodni później, gdy trzeba wystawić korektę.
        """
        if not value:
            return ""
        if not nip_pl.poprawny(value):
            raise serializers.ValidationError(
                "Ten NIP ma nieprawidłową sumę kontrolną. Sprawdź, czy cyfry się nie przestawiły."
            )
        return nip_pl.znormalizuj(value)

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        use_trial = validated_data.pop("use_trial")
        plan = validated_data.pop("plan")

        tenant = Tenant.objects.create(
            name=validated_data["company_name"],
            owner_email=validated_data["email"],
            subscription_status="trial" if use_trial else "inactive",
            subscription_plan="trial" if use_trial else None,
        )

        DaneRozliczeniowe.objects.create(
            tenant=tenant,
            # Bez osobnej nazwy na fakturze bierzemy roboczą - lepsza niż pusta,
            # a klient poprawi ją w ustawieniach, gdy będzie trzeba.
            nazwa=validated_data.get("nazwa_do_faktury") or validated_data["company_name"],
            nip=validated_data.get("nip", ""),
            ulica=validated_data["ulica"],
            kod_pocztowy=validated_data["kod_pocztowy"],
            miasto=validated_data["miasto"],
            kraj=(validated_data.get("kraj") or "PL").upper(),
        )

        user = CustomUser.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["imie"],
            last_name=validated_data["nazwisko"],
            tenant=tenant,
            role="owner",
        )

        return {
            "user": user,
            "use_trial": use_trial,
            "tenant": tenant,
            "plan": plan,
        }


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "role": self.user.role,
            "tenant_id": self.user.tenant_id,
            "tenant_name": self.user.tenant.name,
        }

        return data


class InvitationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvitationToken
        fields = ["email", "role", "duration", "max_users"]

    def create(self, validated_data):
        tenant = self.context["request"].user.tenant
        # Wcześnie, żeby właściciel dowiedział się teraz, a nie po tym, jak
        # pracownik kliknie w link i zobaczy błąd
        sprawdz_limit_miejsc(tenant)
        return InvitationToken.objects.create(tenant=tenant, **validated_data)


class InvitationReadSerializer(serializers.ModelSerializer):
    """
    Zaproszenie widziane z panelu — z gotowym linkiem do skopiowania.

    Sam e-mail nie wystarcza: wysyłka bywa zablokowana albo wiadomość ląduje
    w spamie, a wtedy właściciel nie ma jak przekazać zaproszenia inaczej.
    """

    accept_url = serializers.SerializerMethodField()
    expires_at = serializers.DateTimeField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    seats_left = serializers.SerializerMethodField()

    class Meta:
        model = InvitationToken
        fields = [
            "id",
            "email",
            "role",
            "duration",
            "max_users",
            "users",
            "seats_left",
            "token",
            "accept_url",
            "expires_at",
            "is_valid",
            "created_at",
        ]

    @extend_schema_field(serializers.URLField())
    def get_accept_url(self, obj):
        return f"{settings.FRONTEND_URL.rstrip('/')}/invite/accept/{obj.token}"

    @extend_schema_field(serializers.IntegerField())
    def get_seats_left(self, obj):
        return max(obj.max_users - obj.users, 0)


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            invitation = InvitationToken.objects.get(token=attrs["token"])
        except InvitationToken.DoesNotExist:
            raise serializers.ValidationError("Invalid token.")

        if not invitation.is_valid():
            raise serializers.ValidationError("Token expired or used up.")

        # Ponownie, bo między wystawieniem zaproszenia a jego przyjęciem mogą
        # minąć dni — w tym czasie miejsca mogły się zapełnić albo firma mogła
        # zejść na niższy plan
        sprawdz_limit_miejsc(invitation.tenant)

        attrs["invitation"] = invitation
        return attrs

    def create(self, validated_data):
        invitation = validated_data["invitation"]
        tenant = invitation.tenant

        user = CustomUser.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            tenant=tenant,
            role=invitation.role,
        )

        invitation.use()
        return user


class DocumentSerializer(serializers.ModelSerializer):
    chunk_count = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    preview = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "name",
            "processed",
            "uploaded_at",
            "chunk_count",
            "status",
            "preview",
            "uzywaj_w_wyszukiwaniu",
            "source_url",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_chunk_count(self, obj):
        return obj.chunks.count()

    @extend_schema_field(
        serializers.ChoiceField(choices=["ready", "processed_no_chunks", "processing"])
    )
    def get_status(self, obj):
        if obj.processed:
            if obj.chunks.exists():
                return "ready"
            return "processed_no_chunks"
        return "processing"

    @extend_schema_field(serializers.CharField())
    def get_preview(self, obj):
        return obj.content[:500] if obj.content else ""


class DocumentChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentChunk
        fields = ["id", "content", "created_at"]
        read_only_fields = fields


class WidgetDomainSerializer(serializers.ModelSerializer):
    """Witryna, na której wykryto działający widget."""

    class Meta:
        model = WidgetDomain
        fields = ["id", "host", "first_seen", "last_seen"]
        read_only_fields = fields


class WebsiteSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsiteSource
        fields = ["id", "name", "url", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class PromptLogSerializer(serializers.ModelSerializer):
    is_helpful = serializers.SerializerMethodField()
    # Identyfikator, którym posługuje się usuwanie danych na żądanie — samo
    # conversation_id to klucz techniczny, którego nie da się nigdzie użyć.
    conversation_session_id = serializers.CharField(
        source="conversation.session_id", read_only=True, default=None
    )

    class Meta:
        model = PromptLog
        fields = [
            "id",
            "conversation_id",
            "conversation_session_id",
            "prompt",
            "response",
            "tokens",
            "source",
            "model",
            "created_at",
            "is_helpful",
        ]

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_is_helpful(self, obj):
        msg = ChatMessage.objects.filter(
            conversation=obj.conversation, sender="bot", message=obj.response
        ).first()

        feedback = getattr(msg, "feedback", None)
        return feedback.is_helpful if feedback else None


class ChatFeedbackSerializer(serializers.Serializer):
    """
    Ocena pojedynczej odpowiedzi bota.

    Wiadomości szukamy wyłącznie w obrębie firmy z żądania. Wcześniej zapytanie
    obejmowało wszystkie firmy, więc znając sam identyfikator dało się ocenić
    cudzą rozmowę — a przy publicznym endpoincie dla widgetu byłby to zapis
    między tenantami i sposób na sprawdzanie, jakie identyfikatory istnieją.
    """

    message_id = serializers.IntegerField()
    is_helpful = serializers.BooleanField(required=True)

    def validate(self, data):
        if "is_helpful" not in self.initial_data:
            raise serializers.ValidationError({"is_helpful": "To pole jest wymagane."})
        return data

    def validate_message_id(self, value):
        tenant = self.context.get("tenant")
        if tenant is None:
            raise serializers.ValidationError("Brak kontekstu firmy.")

        message = ChatMessage.objects.filter(
            id=value, sender="bot", conversation__tenant=tenant
        ).first()
        if message is None:
            raise serializers.ValidationError("Nie znaleziono wiadomości od bota.")

        self.context["message"] = message
        return value

    def create(self, validated_data):
        return ChatFeedback.objects.update_or_create(
            message=self.context["message"], defaults={"is_helpful": validated_data["is_helpful"]}
        )[0]


class PublicFAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["question", "answer"]


class ContactRequestCreateSerializer(serializers.Serializer):
    """Dane zostawiane przez odwiedzającego w widgecie — bez pól technicznych."""

    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    contact = serializers.CharField(max_length=200)
    message = serializers.CharField(required=False, allow_blank=True)
    conversation_session_id = serializers.UUIDField(required=False)


class ContactRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactRequest
        # blad_powiadomienia wychodzi do panelu celowo: zapisywanie błędu,
        # którego nikt nie widzi, jest tym samym co jego brak. Właściciel musi
        # wiedzieć, że o tym zapytaniu nie dostał maila — inaczej czeka na
        # powiadomienie, które nigdy nie przyszło.
        fields = [
            "id",
            "name",
            "contact",
            "message",
            "handled",
            "created_at",
            "powiadomiono_at",
            "blad_powiadomienia",
        ]
        read_only_fields = [
            "id",
            "name",
            "contact",
            "message",
            "created_at",
            "powiadomiono_at",
            "blad_powiadomienia",
        ]


class FAQSerializer(serializers.ModelSerializer):
    """Wersja do zarządzania z panelu — z id, żeby dało się edytować i usuwać."""

    class Meta:
        model = FAQ
        fields = ["id", "question", "answer"]
        read_only_fields = ["id"]
