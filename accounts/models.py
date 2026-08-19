import uuid
from datetime import timedelta
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator

from accounts.plans import PROGI_ALERTOW


class WidgetPosition(models.TextChoices):
    RIGHT = "right", "Right"
    LEFT = "left", "Left"


class BrandingMode(models.TextChoices):
    SMART = "smart", "Smart (domyślna marka)"
    WHITE_LABEL = "white_label", "White-label (marka klienta)"


class UserRole(models.TextChoices):
    OWNER = "owner", "Owner"
    EMPLOYEE = "employee", "Employee"
    VIEWER = "viewer", "Viewer"


class InvitationDuration(models.TextChoices):
    ONE_HOUR = "1h", "1 Hour"
    TWELVE_HOURS = "12h", "12 Hours"
    ONE_DAY = "1d", "1 Day"
    ONE_WEEK = "7d", "7 Days"

# Języki, w których widget może odpowiadać. Celowo krótka lista: badanie rynku
# wskazuje PL/EN jako wymóg podstawowy, a UA/DE jako kolejny krok. Każdy dodany
# język to nie tylko tłumaczenie odpowiedzi, ale też obietnica obsługi po
# eskalacji do człowieka — dlatego decyduje o niej klient, nie model.
WIDGET_LANGUAGES = {
    "pl": "polski",
    "en": "angielski",
    "uk": "ukraiński",
    "de": "niemiecki",
    "ru": "rosyjski",
    "cs": "czeski",
}

# Forma używana w promptcie. Osobna, bo "odpowiadaj w języku polski" to
# widocznie zła polszczyzna, a prompt jest najważniejszym tekstem w produkcie.
WIDGET_LANGUAGE_ADVERBS = {
    "pl": "po polsku",
    "en": "po angielsku",
    "uk": "po ukraińsku",
    "de": "po niemiecku",
    "ru": "po rosyjsku",
    "cs": "po czesku",
}


class LanguageMode(models.TextChoices):
    """
    Jak bot dobiera język odpowiedzi.

    FIXED to nie to samo co AUTO z jednym zaznaczonym językiem, choć efekt bywa
    ten sam: FIXED jest decyzją klienta ("obsługuję wyłącznie polski"), więc
    zaznaczenie kolejnych języków go nie zmienia, dopóki klient sam nie przełączy
    trybu.
    """
    FIXED = "fixed", "Zawsze jeden język"
    AUTO = "auto", "Dopasuj do języka pytania"


def generate_api_key():
    return uuid.uuid4()


class Tenant(models.Model):
    name = models.CharField(max_length=100)
    api_key = models.UUIDField(default=generate_api_key, unique=True, editable=False)
    regulamin = models.TextField(blank=True, null=True)
    gpt_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="Unikalny prompt charakterystyczny dla firmy (np. 'Jesteśmy hurtownią elektryczną...')"
    )

    # OpenAI
    openai_api_key = models.CharField(max_length=128, blank=True, null=True)

    # Widget
    widget_position = models.CharField(max_length=25, choices=WidgetPosition.choices, default=WidgetPosition.RIGHT)
    widget_color = models.CharField(max_length=20, default="#000000")
    widget_title = models.CharField(max_length=100, default="Chatbot")
    branding_mode = models.CharField(max_length=20, choices=BrandingMode.choices, default=BrandingMode.SMART)
    widget_logo = models.FileField(upload_to="widget_branding/", null=True, blank=True)
    widget_avatar = models.FileField(upload_to="widget_branding/", null=True, blank=True)
    widget_footer_text = models.CharField(max_length=100, blank=True, default="")

    # Środkowy próg brandingu z cennika. Klient planu Grow kupuje przede
    # wszystkim to, żeby jego widget nie reklamował cudzej firmy — własne logo
    # i nazwa to potrzeba dopiero na Pro. Bez tego pola Grow nie różnił się
    # od Start niczym poza limitem wiadomości.
    widget_hide_branding = models.BooleanField(
        default=False,
        help_text='Ukryć stopkę "Powered by Sm-art" (plan Grow i wyżej).',
    )

    # Puste okno czatu z samym polem tekstowym nie podpowiada, o co można zapytać,
    # więc odwiedzający najczęściej je zamyka. Powitanie i gotowe pytania dają
    # pierwszy krok bez wymyślania go samemu.
    widget_welcome_message = models.TextField(
        blank=True,
        default="",
        help_text="Pierwsza wiadomość bota. Puste = okno otwiera się bez powitania.",
    )
    widget_suggested_questions = models.TextField(
        blank=True,
        default="",
        help_text="Propozycje pytań startowych, po jednym w wierszu (pokazujemy do 4).",
    )

    MAX_SUGGESTED_QUESTIONS = 4

    def suggested_questions(self):
        """Pytania startowe jako lista, bez pustych wierszy."""
        lines = [
            line.strip()
            for line in (self.widget_suggested_questions or "").splitlines()
            if line.strip()
        ]
        return lines[: self.MAX_SUGGESTED_QUESTIONS]

    # Języki, w których bot może odpowiadać. Prompt miał zaszyte "odpowiadaj po
    # polsku", więc anglojęzyczny odwiedzający dostawał polską odpowiedź na
    # angielskie pytanie. Język pytania rozpoznajemy w kodzie (api.utils.language),
    # ale wyłącznie w obrębie tej listy — inaczej bot odpowiadałby w dowolnym
    # języku świata, także takim, którego firma nie obsłuży przy eskalacji.
    widget_languages = models.CharField(
        max_length=64,
        default="pl",
        help_text="Kody języków po przecinku, np. pl,en. Używane tylko w trybie 'auto'.",
    )
    widget_language_mode = models.CharField(
        max_length=10,
        choices=LanguageMode.choices,
        default=LanguageMode.AUTO,
        help_text="Czy bot trzyma się jednego języka, czy dopasowuje go do pytania.",
    )
    # Osobne pole, bo wcześniej rolę domyślnego pełnił pierwszy element listy —
    # a listę klient zaznacza checkboxami, więc o domyślnym języku decydowała
    # kolejność klikania. Klient nie miał na to wpływu ani tego nie widział.
    widget_default_language = models.CharField(
        max_length=5,
        choices=[(kod, nazwa) for kod, nazwa in WIDGET_LANGUAGES.items()],
        default="pl",
        help_text=(
            "W trybie 'jeden język' — język odpowiedzi. W trybie 'auto' — język "
            "zapasowy, gdy pytanie przyjdzie w języku spoza listy."
        ),
    )

    def languages(self):
        """Dozwolone języki. Zawsze co najmniej jeden."""
        kody = [
            kod.strip().lower()
            for kod in (self.widget_languages or "").replace(";", ",").split(",")
            if kod.strip()
        ]
        znane = [kod for kod in kody if kod in WIDGET_LANGUAGES]
        # Bez tego zabezpieczenia literówka w konfiguracji zostawiłaby bota
        # bez jakiegokolwiek języka i model wybierałby go sobie sam
        return znane or [self.default_language()]

    def default_language(self):
        """Język zapasowy. Literówka w konfiguracji nie może zostawić bota bez języka."""
        if self.widget_default_language in WIDGET_LANGUAGES:
            return self.widget_default_language
        return "pl"

    def uses_fixed_language(self):
        return self.widget_language_mode == LanguageMode.FIXED

    # Wiadomość proaktywna — zaczepka pokazywana sama z siebie, zanim odwiedzający
    # cokolwiek napisze. Celowo gotowy tekst, nie odpowiedź modelu: nie zużywa
    # limitu planu ani pieniędzy za API, a dopiero reakcja na nią jest normalną,
    # płatną wiadomością. Dzięki temu może działać u wszystkich klientów.
    widget_proactive_enabled = models.BooleanField(
        default=False,
        help_text="Czy pokazywać zaczepkę odwiedzającemu, który nie zaczął rozmowy.",
    )
    widget_proactive_delay_seconds = models.PositiveIntegerField(
        default=30,
        help_text="Po ilu sekundach na stronie pokazać zaczepkę.",
    )
    # Słownik kod języka -> tekst. Języka nie da się tu wykryć z wiadomości,
    # bo wiadomości jeszcze nie ma — widget bierze go z atrybutu lang strony
    # klienta, czyli z jej wersji językowej.
    widget_proactive_texts = models.JSONField(
        default=dict,
        blank=True,
        help_text='Teksty zaczepki per język, np. {"pl": "Pomóc w czymś?"}.',
    )

    MAX_PROACTIVE_TEXT = 200

    def proactive_texts(self):
        """Teksty zaczepki, bez pustych i obciętych do rozsądnej długości."""
        surowe = self.widget_proactive_texts or {}
        if not isinstance(surowe, dict):
            return {}
        return {
            kod: str(tekst).strip()[: self.MAX_PROACTIVE_TEXT]
            for kod, tekst in surowe.items()
            if kod in WIDGET_LANGUAGES and str(tekst).strip()
        }

    def proactive_text_for(self, kod_jezyka=None):
        """
        Zaczepka dla danej wersji językowej strony.

        Kolejność: dokładne dopasowanie, potem język domyślny firmy, na końcu
        cokolwiek uzupełnionego — pusty wynik oznacza brak zaczepki.
        """
        teksty = self.proactive_texts()
        if not teksty:
            return ""
        # "en-GB" z atrybutu lang ma trafić na "en"
        kod = (kod_jezyka or "").strip().lower().replace("_", "-").split("-")[0]
        for kandydat in (kod, self.default_language()):
            if kandydat in teksty:
                return teksty[kandydat]
        return next(iter(teksty.values()))

    def language_names(self):
        """Nazwy dozwolonych języków — do pokazania w panelu."""
        return [WIDGET_LANGUAGES[kod] for kod in self.languages()]

    def language_adverbs(self):
        """Formy "po polsku", "po angielsku" — do wstawienia w prompt."""
        return [WIDGET_LANGUAGE_ADVERBS[kod] for kod in self.languages()]

    # Email
    owner_email = models.EmailField(blank=True, null=True)

    # Powiadomienie o KAŻDEJ rozpoczętej rozmowie, nie tylko o zostawionym
    # kontakcie. Domyślnie wyłączone i to jest świadome: przy realnym ruchu
    # mail od każdego odwiedzającego zamienia się w szum, a wtedy właściciel
    # przestaje czytać także te powiadomienia, które niosą zapytanie.
    # Włączone ma sens na początku, gdy rozmów jest kilka dziennie i każda
    # jest ciekawa.
    powiadom_o_rozmowie = models.BooleanField(
        default=False,
        verbose_name="Powiadamiaj o każdej rozpoczętej rozmowie",
    )

    # RODO — rozmowy odwiedzających to dane osobowe (treść pytań, adres IP, kontakty
    # zostawione w formularzu). Administratorem jest firma-klient, my przetwarzamy
    # w jej imieniu, więc okres przechowywania musi być jej decyzją, nie naszą.
    data_retention_days = models.PositiveIntegerField(
        default=90,
        help_text="Po ilu dniach automatycznie usuwać rozmowy i logi. 0 = nie usuwaj.",
    )
    privacy_policy_url = models.URLField(
        blank=True,
        default="",
        help_text="Link do polityki prywatności pokazywany w widgecie.",
    )

    # Subskrypcje
    subscription_plan = models.CharField(max_length=100, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_status = models.CharField(max_length=50, blank=True, null=True)

    # Token
    current_token_usage = models.PositiveIntegerField(default=0)
    token_limit = models.PositiveIntegerField(default=100000, validators=[MinValueValidator(1000)])

    created_at = models.DateTimeField(auto_now_add=True)

    def has_active_subscription(self):
        return self.subscription_status in ["active", "trialing"]

    def token_limit_exceeded(self):
        return self.current_token_usage >= self.token_limit

    def __str__(self):
        return f"{self.name} (API Key: {self.api_key})"


class CustomUser(AbstractUser):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="users")
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.VIEWER)

    def __str__(self):
        return f"{self.username} [{self.tenant.name}]"


class InvitationToken(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.EMPLOYEE)
    duration = models.CharField(max_length=10, choices=InvitationDuration.choices, default=InvitationDuration.ONE_DAY)
    created_at = models.DateTimeField(auto_now_add=True)
    max_users = models.PositiveIntegerField(default=1)
    users = models.PositiveIntegerField(default=0)

    DURATION_DELTAS = {
        InvitationDuration.ONE_HOUR: timedelta(hours=1),
        InvitationDuration.TWELVE_HOURS: timedelta(hours=12),
        InvitationDuration.ONE_DAY: timedelta(days=1),
        InvitationDuration.ONE_WEEK: timedelta(days=7),
    }

    @property
    def expires_at(self):
        """
        Termin ważności. None dla niezapisanego zaproszenia — created_at
        uzupełnia się dopiero przy zapisie, a formularz dodawania w adminie
        wyświetla to pole zanim to nastąpi.
        """
        if not self.created_at:
            return None
        delta = self.DURATION_DELTAS.get(self.duration, timedelta(days=1))
        return self.created_at + delta

    def is_valid(self):
        expires_at = self.expires_at
        if expires_at is None:
            return False
        return expires_at > timezone.now() and self.users < self.max_users

    def use(self):
        self.users += 1
        self.save()

    def __str__(self):
        return f"Invitation for {self.email} [{self.role}] ({self.tenant.name})"


class Subscription(models.Model):

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan_type = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    # Nowe pola dla limitów
    message_limit = models.PositiveIntegerField(
        default=1000,
        verbose_name="Limit wiadomości/miesiąc",
        help_text="Miesięczny limit wiadomości dla wszystkich chatbotów firmy"
    )

    current_message_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Liczba użytych wiadomości"
    )

    # Cykl rozliczeniowy
    billing_cycle_start = models.DateField(
        auto_now_add=True,
        verbose_name="Start cyklu rozliczeniowego"
    )

    # Najwyższy próg zużycia, o którym już powiadomiliśmy w tym cyklu.
    # Bez tego pola alert leciałby przy każdej kolejnej wiadomości powyżej progu,
    # a klient nauczyłby się je ignorować dokładnie wtedy, gdy zaczynają być ważne.
    alert_threshold_sent = models.PositiveIntegerField(
        default=0,
        verbose_name="Ostatnio wysłany próg alertu (%)",
    )

    def usage_percent(self):
        """Zużycie limitu w procentach. Bez limitu nie ma czego liczyć."""
        if not self.message_limit:
            return 0
        return int(self.current_message_count / self.message_limit * 100)

    def prog_do_powiadomienia(self):
        """
        Najwyższy przekroczony próg, o którym jeszcze nie powiadomiliśmy.

        Zwraca None, gdy nie ma o czym informować. Bierzemy najwyższy, a nie
        kolejny: przy skokowym zużyciu klient dostanie jedną wiadomość
        "wyczerpałeś limit", a nie trzy pod rząd.
        """
        procent = self.usage_percent()
        przekroczone = [
            prog for prog in PROGI_ALERTOW
            if procent >= prog and prog > self.alert_threshold_sent
        ]
        return max(przekroczone) if przekroczone else None

    # Metody walidacyjne
    def has_message_quota(self):
        """Czy firma ma dostępne wiadomości w bieżącym cyklu"""
        return self.current_message_count < self.message_limit

    def reset_usage(self):
        """Resetuj licznik na początku nowego cyklu"""
        self.current_message_count = 0
        self.billing_cycle_start = timezone.now().date()
        # Bez wyzerowania progu klient nie dostałby już nigdy żadnego alertu:
        # w nowym cyklu zużycie startuje od zera, więc nic nie przekroczyłoby
        # progu zapamiętanego z poprzedniego miesiąca.
        self.alert_threshold_sent = 0
        self.save(update_fields=[
            'current_message_count', 'billing_cycle_start', 'alert_threshold_sent',
        ])

    def increment_usage(self):
        """Atomowe zwiększenie licznika wiadomości"""
        Subscription.objects.filter(
            pk=self.pk
        ).update(
            current_message_count=models.F('current_message_count') + 1
        )
        self.refresh_from_db()

        # Milczące wyczerpanie limitu wygląda dla klienta jak awaria chatbota:
        # widget przestaje odpowiadać, a on dowiaduje się o tym od odwiedzających.
        prog = self.prog_do_powiadomienia()
        if prog:
            from accounts.tasks import powiadom_o_zuzyciu
            from documents.utils.queue import enqueue

            # Zapisujemy próg przed wysyłką, nie po. Awaria poczty nie może
            # zamienić jednego alertu w alert przy każdej kolejnej wiadomości.
            self.alert_threshold_sent = prog
            self.save(update_fields=['alert_threshold_sent'])
            enqueue(powiadom_o_zuzyciu, self.pk, prog)


class WidgetDomain(models.Model):
    """
    Witryna, na której klient osadził widget.

    Cennik obiecuje 1, 3 albo 10 domen, ale dotąd nic nie wiedziało, gdzie
    widgety faktycznie działają. Rejestrujemy je same, przy pierwszym zapytaniu
    z danej witryny — klient nie musi niczego konfigurować, a my zyskujemy
    dwie rzeczy: policzalny limit oraz ochronę klucza API. Klucz jest widoczny
    w kodzie strony klienta, więc bez tej listy każdy mógł go skopiować
    i zużywać cudzy limit na własnej stronie.

    Adres bierzemy z nagłówka Origin, którego przeglądarka nie pozwala podrobić
    z poziomu strony. Nie z parametru w zapytaniu — ten byłby tylko deklaracją.
    """
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="widget_domains"
    )
    host = models.CharField(
        max_length=255,
        help_text="Nazwa hosta bez schematu i bez www, np. sklep.pl",
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("tenant", "host")
        ordering = ["host"]

    def __str__(self):
        return f"{self.host} ({self.tenant.name})"
