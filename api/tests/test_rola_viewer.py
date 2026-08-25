"""
Rola `viewer`: czyta wszystko, nie zapisuje niczego.

Rola istniała w modelu od początku, ale nie miała czego oglądać. Widoki bazy
wiedzy, ustawień widgetu, prywatności i diagnostyki trzymały IsOwnerOrEmployee
na całej klasie — razem z metodą GET. Zmierzone przed poprawką: `viewer`
dostawał 200 na trzech z dziesięciu endpointów panelu.

Było to niespójne podwójnie. Po pierwsze, obserwator, który nie może
obserwować, nie pełni żadnej funkcji. Po drugie, najwrażliwsze dane w systemie
— treść rozmów z klientami — `viewer` czytał od zawsze przez /api/chat/logs/,
więc odmawianie mu wglądu w cennik własnej firmy niczego nie chroniło.

Ten plik pilnuje obu połówek umowy naraz. Sam test odczytu przepuściłby
regresję, w której ktoś podmienia klasę na IsTenantMember i otwiera zapis;
sam test zapisu przepuściłby powrót do IsOwnerOrEmployee i zamknięcie odczytu.
"""
import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant, UserRole
from chat.models import FAQ


@pytest.fixture
def firma(db):
    firma = Tenant.objects.create(name="Firma testowa", owner_email="wl@firma.pl")
    Subscription.objects.create(
        tenant=firma, plan_type="grow",
        start_date="2026-01-01", end_date="2027-01-01",
        message_limit=8000,
    )
    return firma


def konto(firma, rola, login):
    return CustomUser.objects.create_user(
        username=login, email=login, password="x", tenant=firma, role=rola,
    )


def klient(uzytkownik):
    k = APIClient()
    k.force_authenticate(user=uzytkownik)
    k.credentials(HTTP_X_API_KEY=str(uzytkownik.tenant.api_key))
    return k


# Odczyt, do którego `viewer` ma prawo. Każdy z tych adresów zwracał 403
# przed rozdzieleniem uprawnień na metody.
DO_ODCZYTU = [
    "/api/knowledge/",
    "/api/privacy/",
    "/api/widget-settings/mine/",
    "/api/diagnostyka/zadania/",
    "/api/diagnostyka/adres/",
    "/api/faq/",
]

# Zapis, którego `viewer` mieć nie może.
DO_ZAPISU = [
    ("patch", "/api/knowledge/", {"gpt_prompt": "przejęte"}),
    ("patch", "/api/widget-settings/mine/", {"widget_title": "przejęte"}),
    ("patch", "/api/privacy/", {"retention_days": 7}),
    ("post", "/api/faq/", {"question": "p", "answer": "o"}),
]


@pytest.mark.django_db
class TestOdczytu:
    @pytest.mark.parametrize("adres", DO_ODCZYTU)
    def test_viewer_czyta(self, firma, adres):
        odp = klient(konto(firma, UserRole.VIEWER, "v@firma.pl")).get(adres)

        assert odp.status_code == 200, (
            f"{adres} odmówił obserwatorowi odczytu (HTTP {odp.status_code})"
        )

    @pytest.mark.parametrize("adres", DO_ODCZYTU)
    def test_wlasciciel_dalej_czyta(self, firma, adres):
        """Rozdzielenie uprawnień nie mogło niczego zabrać rolom wyższym."""
        odp = klient(konto(firma, UserRole.OWNER, "w@firma.pl")).get(adres)

        assert odp.status_code == 200

    def test_niezalogowany_nie_czyta(self, firma):
        """
        Poprzednia klasa (ReadOnlyOrOwner) przy metodzie bezpiecznej zwracała
        True bez patrzenia, kto pyta. Nie była używana, ale leżała gotowa —
        dlatego została usunięta, a nie poprawiona. Ten test pilnuje, żeby
        nowa nie odziedziczyła tamtego zachowania.
        """
        for adres in DO_ODCZYTU:
            odp = APIClient().get(adres)

            assert odp.status_code in (401, 403), (
                f"{adres} wpuścił niezalogowanego (HTTP {odp.status_code})"
            )


@pytest.mark.django_db
class TestZapisu:
    @pytest.mark.parametrize("metoda,adres,dane", DO_ZAPISU)
    def test_viewer_nie_zapisuje(self, firma, metoda, adres, dane):
        odp = getattr(klient(konto(firma, UserRole.VIEWER, "v@firma.pl")), metoda)(
            adres, dane, format="json",
        )

        assert odp.status_code == 403, (
            f"{metoda.upper()} {adres} przepuścił obserwatora (HTTP {odp.status_code})"
        )

    def test_viewer_nie_zmienia_danych_mimo_odpowiedzi(self, firma):
        """
        Kod odpowiedzi to za mało: widok mógłby zapisać i dopiero potem odmówić.
        Sprawdzamy stan bazy, nie tylko HTTP.
        """
        firma.gpt_prompt = "oryginał"
        firma.save(update_fields=["gpt_prompt"])

        klient(konto(firma, UserRole.VIEWER, "v@firma.pl")).patch(
            "/api/knowledge/", {"gpt_prompt": "przejęte"}, format="json",
        )

        firma.refresh_from_db()
        assert firma.gpt_prompt == "oryginał"

    def test_pracownik_zapisuje(self, firma):
        """Zacieśnienie nie mogło zablokować roli, która ma prawo zapisu."""
        odp = klient(konto(firma, UserRole.EMPLOYEE, "p@firma.pl")).post(
            "/api/faq/", {"question": "p", "answer": "o"}, format="json",
        )

        assert odp.status_code == 201
        assert FAQ.objects.filter(tenant=firma, question="p").exists()


@pytest.mark.django_db
class TestHurtowegoEksportu:
    """
    Eksport całej historii rozmów do CSV stał na IsTenantMember, więc `viewer`
    mógł ją wynieść jednym żądaniem. Te same wiersze widać wprawdzie przez
    /api/chat/logs/, ale stronicowany podgląd w panelu a zrzut całości to inny
    profil ryzyka — a rola nazywa się „podgląd", nie „eksport".
    """

    def test_viewer_nie_eksportuje(self, firma):
        odp = klient(konto(firma, UserRole.VIEWER, "v@firma.pl")).get("/api/chat/export/")

        assert odp.status_code == 403

    def test_wlasciciel_eksportuje(self, firma):
        odp = klient(konto(firma, UserRole.OWNER, "w@firma.pl")).get("/api/chat/export/")

        assert odp.status_code == 200
