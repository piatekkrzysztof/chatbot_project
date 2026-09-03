"""
Próba odtworzenia z kopii zapasowej.

Kategoria ryzyka: OSTATNIA DESKA RATUNKU. `backup_data` kończy się zdaniem
„Odtworzenie: manage.py loaddata <plik>". Ta obietnica nigdy nie została
sprawdzona - a kopia zapasowa, z której nikt nigdy nie odtwarzał, nie jest
kopią zapasową, tylko plikiem, co do którego mamy nadzieję.

Ten plik jest próbą generalną zapisaną jako test, a nie jednorazowym
ćwiczeniem: jednorazowe przechodzi raz i przestaje cokolwiek znaczyć przy
najbliższej zmianie modelu. Tutaj każdy nowy model, który się nie odtwarza,
zapala czerwone światło przy pierwszym uruchomieniu CI.

Przebieg jest dokładnie taki, jaki byłby po awarii:
zapełniona baza -> zrzut -> utrata WSZYSTKIEGO -> odtworzenie -> sprawdzenie.
"""

import json
import os
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import DaneRozliczeniowe, Subscription, Tenant
from chat.models import FAQ, ChatMessage, Conversation
from documents.models import Document, DocumentChunk


@pytest.fixture
def dane_do_odtworzenia(db, django_user_model):
    """
    Przekrój przez rzeczy, których utrata naprawdę boli.

    Nie „jakiś obiekt", tylko po jednym z każdej kategorii, która ma inny
    sposób psucia się przy odtwarzaniu: klucze obce, pole wektorowe pgvector,
    relacja jeden-do-jednego, dane osobowe i rozliczeniowe.
    """
    firma = Tenant.objects.create(name="Rowerownia", owner_email="szef@rowerownia.pl")

    wlascicielka = django_user_model.objects.create_user(
        username="szef@rowerownia.pl",
        email="szef@rowerownia.pl",
        password="tajne-haslo-2026",
        tenant=firma,
        role="owner",
    )

    dzis = timezone.localdate()
    Subscription.objects.create(
        tenant=firma,
        plan_type="pro",
        start_date=dzis,
        end_date=dzis + timezone.timedelta(days=30),
        is_active=True,
        billing_cycle_start=dzis,
    )

    DaneRozliczeniowe.objects.create(
        tenant=firma,
        nazwa="Rowerownia Krakowska Anna Nowak",
        nip="5260250274",
        ulica="Krakowska 12",
        kod_pocztowy="31-000",
        miasto="Kraków",
    )

    dokument = Document.objects.create(
        tenant=firma,
        name="Cennik serwisu",
        content="Przeglad podstawowy 120 zl. Wymiana lancucha 80 zl.",
        processed=True,
    )

    # Wektor to najbardziej podejrzany element calego zrzutu: 1536 liczb
    # zmiennoprzecinkowych w typie, ktorego JSON nie zna. Wartosci sa
    # rozpoznawalne, zeby dalo sie sprawdzic nie tylko DlUGOSC, ale i tresc.
    DocumentChunk.objects.create(
        document=dokument,
        content="Przeglad podstawowy 120 zl.",
        embedding=[0.5] * 1535 + [0.25],
    )

    FAQ.objects.create(
        tenant=firma,
        question="Jakie macie godziny otwarcia?",
        answer="Poniedzialek-piatek 9-18.",
    )

    rozmowa = Conversation.objects.create(tenant=firma, user_identifier="gosc-42")
    ChatMessage.objects.create(
        conversation=rozmowa, sender="user", message="Ile kosztuje przeglad?"
    )
    ChatMessage.objects.create(conversation=rozmowa, sender="bot", message="120 zl.", source="faq")

    return {"firma": firma, "wlascicielka": wlascicielka, "dokument": dokument}


def _policz_wszystko():
    return {
        "firmy": Tenant.objects.count(),
        "subskrypcje": Subscription.objects.count(),
        "dane_rozliczeniowe": DaneRozliczeniowe.objects.count(),
        "dokumenty": Document.objects.count(),
        "fragmenty": DocumentChunk.objects.count(),
        "faq": FAQ.objects.count(),
        "rozmowy": Conversation.objects.count(),
        "wiadomosci": ChatMessage.objects.count(),
    }


@pytest.mark.django_db(transaction=True)
class TestProbyOdtworzenia:
    """
    `transaction=True` jest tu konieczne, nie kosmetyczne.

    Odtwarzanie czysci baze i wczytuje dane we wlasnych transakcjach. W zwyklym
    tescie, opakowanym w jedna transakcje z wycofaniem, sprawdzalibysmy stan,
    ktory nigdy nie trafil do bazy - czyli prob^e generalna na atrapie.
    """

    def test_pelny_cykl_utraty_i_odtworzenia(self, dane_do_odtworzenia, tmp_path):
        plik = tmp_path / "kopia.json"

        call_command("backup_data", output=str(plik))
        przed = _policz_wszystko()
        assert przed["firmy"] == 1, "dane testowe nie powstaly"

        # Utrata. `flush` czysci wszystkie tabele - to jest najblizsza
        # symulacja "baza przepadla", jaka da sie zrobic bez kasowania bazy.
        call_command("flush", interactive=False, verbosity=0)
        assert Tenant.objects.count() == 0, "flush nie wyczyscil bazy"

        call_command("loaddata", str(plik), verbosity=0)

        assert _policz_wszystko() == przed

    def test_wektor_pgvector_wraca_bez_zmian(self, dane_do_odtworzenia, tmp_path):
        """
        Najważniejszy pojedynczy test w tym pliku.

        Embedding to 1536 liczb w typie, ktorego JSON nie zna. Gdyby zrzut
        gubil go po cichu albo zmienial precyzje, kopia wygladalaby na dobra:
        wiersze sa, tresc jest, liczby sie zgadzaja. Wyszloby dopiero przy
        pierwszym pytaniu do bota po odtworzeniu - czyli w najgorszym momencie.
        """
        plik = tmp_path / "kopia.json"
        call_command("backup_data", output=str(plik))

        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(plik), verbosity=0)

        fragment = DocumentChunk.objects.get()
        assert len(fragment.embedding) == 1536
        assert fragment.embedding[0] == pytest.approx(0.5)
        assert fragment.embedding[-1] == pytest.approx(0.25)

    def test_logowanie_dziala_po_odtworzeniu(self, dane_do_odtworzenia, tmp_path, client):
        """
        Odtworzone konto musi dac sie uzyc, nie tylko policzyc.

        Skrot hasla przechodzi przez JSON jako zwykly tekst i nic go nie
        sprawdza po drodze. Gdyby sie po drodze zepsul, tabela uzytkownikow
        wygladalaby na kompletna, a nikt nie moglby wejsc do panelu.
        """
        plik = tmp_path / "kopia.json"
        call_command("backup_data", output=str(plik))

        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(plik), verbosity=0)

        odpowiedz = client.post(
            "/api/accounts/login/",
            {"username": "szef@rowerownia.pl", "password": "tajne-haslo-2026"},
            content_type="application/json",
        )
        assert odpowiedz.status_code == 200, odpowiedz.content

    def test_widget_odpowiada_po_odtworzeniu(self, dane_do_odtworzenia, tmp_path, client):
        """
        Klucz API musi zostac ten sam.

        Klucz jest wklejony we fragment na stronie klienta. Gdyby odtworzenie
        nadalo nowy, kazdy widget u kazdego klienta trzeba by wymieniac recznie
        - a to znaczy telefon do kazdego z osobna w dniu po awarii.
        """
        firma = dane_do_odtworzenia["firma"]
        klucz_przed = str(firma.api_key)

        plik = tmp_path / "kopia.json"
        call_command("backup_data", output=str(plik))

        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(plik), verbosity=0)

        assert str(Tenant.objects.get().api_key) == klucz_przed

    def test_odtwarzanie_nie_zleca_generowania_embeddingow(self, dane_do_odtworzenia, tmp_path):
        """
        Najdroższy błąd, jaki ta próba znalazła.

        Fragmenty wczytuja sie z pliku PO dokumentach, wiec w chwili zapisu
        dokumentu `chunks.exists()` jest falszywe dla kazdego z nich. Bez
        sprawdzenia flagi `raw` odtwarzanie zlecalo generowanie embeddingow
        dla CALEJ bazy - platne wywolania OpenAI dla danych, ktorych gotowe
        wektory leza dwa ekrany dalej w tym samym pliku.

        Przy nieczynnym Celery `enqueue` wykonuje zadanie na miejscu, wiec samo
        odtwarzanie robilo te wywolania w locie: dlugo, drogo i z ryzykiem
        przerwania w polowie - w dniu, w ktorym wszystko juz raz padlo.
        """
        plik = tmp_path / "kopia.json"
        call_command("backup_data", output=str(plik))
        call_command("flush", interactive=False, verbosity=0)

        with patch("documents.signals.enqueue") as zlecenie:
            call_command("loaddata", str(plik), verbosity=0)

        assert zlecenie.call_count == 0, (
            f"odtwarzanie zlecilo {zlecenie.call_count} zadan - "
            "kazde z nich to wywolanie OpenAI za dane, ktore wlasnie wczytujemy"
        )

    def test_zwykly_zapis_dokumentu_dalej_zleca_przetwarzanie(self, db, dane_do_odtworzenia):
        # Druga strona tej samej zmiany: wyjscie przy `raw` nie moze wylaczyc
        # przetwarzania przy normalnym wgrywaniu dokumentu przez klienta.
        firma = dane_do_odtworzenia["firma"]

        with patch("documents.signals.enqueue") as zlecenie:
            Document.objects.create(
                tenant=firma, name="Nowy cennik", content="tresc", processed=True
            )

        assert zlecenie.call_count == 1

    def test_zrzut_nie_zawiera_tabel_odtwarzanych_przez_migracje(
        self, dane_do_odtworzenia, tmp_path
    ):
        # Typy zawartosci i uprawnienia tworza sie same przy migracjach.
        # W zrzucie nie tylko zajmuja miejsce, ale KOLIDUJA z tym, co migracje
        # juz zalozyly - i wtedy odtwarzanie przerywa sie w polowie.
        plik = tmp_path / "kopia.json"
        call_command("backup_data", output=str(plik))

        with open(plik, encoding="utf-8") as otwarty:
            modele = {wpis["model"] for wpis in json.load(otwarty)}

        assert "contenttypes.contenttype" not in modele
        assert "auth.permission" not in modele
        assert "sessions.session" not in modele


@pytest.mark.django_db
class TestZabezpieczen:
    def test_pusty_zrzut_nie_nadpisuje_dobrej_kopii(self, db, tmp_path):
        """
        Baza pusta po awarii to najgorszy moment na zrobienie kopii.

        Gdyby harmonogram zdazyl wtedy nadpisac ostatnia dobra kopie pustym
        plikiem, awaria odwracalna zamienilaby sie w nieodwracalna.
        """
        from django.core.management.base import CommandError

        plik = tmp_path / "kopia.json"
        plik.write_text('[{"model": "wazne.dane"}]', encoding="utf-8")

        with pytest.raises(CommandError):
            call_command("backup_data", output=str(plik))

        # Poprzednia kopia nietknieta.
        assert "wazne.dane" in plik.read_text(encoding="utf-8")

    def test_kopia_powstaje_w_katalogu_ktorego_nie_ma(self, dane_do_odtworzenia, tmp_path):
        sciezka = tmp_path / "gleboko" / "schowane" / "kopia.json"

        call_command("backup_data", output=str(sciezka))

        assert os.path.exists(sciezka)
