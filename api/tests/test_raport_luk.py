"""
Cotygodniowy raport luk w wiedzy.

To jedyna rzecz, jaką ten produkt mówi klientowi o jego własnych klientach,
a nie o sobie. Panel odpowiada na „czy chatbot działa"; ten list odpowiada
na „czego ludzie u Ciebie szukali i nie znaleźli".

Testujemy trzy rzeczy, na których stoi jego użyteczność: że powtórzone
pytanie liczy się jako jedno (ale pilniejsze), że okno to naprawdę tydzień,
i że milczenie jest zarezerwowane dla braku luk — a nie dla awarii.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from accounts.models import Tenant
from chat.models import PromptLog
from chat.raport_luk import luki_w_wiedzy, wyslij_raport
from chat.tasks import wyslij_raporty_tygodniowe


def firma(**kw):
    kw.setdefault("owner_email", "wlasciciel@firma.pl")
    return Tenant.objects.create(name="Dwór Weselny", **kw)


def pytanie(tenant, tresc, source="gpt", dni_temu=0):
    wpis = PromptLog.objects.create(
        tenant=tenant, model="gpt-4o-mini", prompt=tresc, source=source
    )
    if dni_temu:
        # created_at ma auto_now_add, więc datę trzeba nadpisać po zapisie
        nowa = timezone.now() - timedelta(days=dni_temu)
        PromptLog.objects.filter(pk=wpis.pk).update(created_at=nowa)
    return wpis


@pytest.mark.django_db
class TestGrupowania:
    def test_powtorzone_pytanie_to_jedna_pozycja_z_licznikiem(self):
        """Sedno. Surowa lista dziesięciu wpisów bywa jednym pytaniem zadanym
        dziesięć razy — i wygląda wtedy na dziesięć problemów zamiast na jeden,
        za to pilny."""
        t = firma()
        for _ in range(3):
            pytanie(t, "Czy organizujecie chrzciny?")

        luki = luki_w_wiedzy(t)

        assert len(luki) == 1
        assert luki[0]["ile"] == 3

    def test_roznice_w_zapisie_nie_rozbijaja_pozycji(self):
        """„Robicie chrzciny?" i „robicie  chrzciny ?" to jedno pytanie.
        Grupowanie po surowej treści rozbiłoby je na dwie pozycje."""
        t = firma()
        pytanie(t, "Robicie chrzciny?")
        pytanie(t, "robicie  chrzciny?")

        luki = luki_w_wiedzy(t)

        assert len(luki) == 1
        assert luki[0]["ile"] == 2

    def test_najczestsze_na_gorze(self):
        """Kolejność jest treścią: mówi, co uzupełnić najpierw."""
        t = firma()
        pytanie(t, "Rzadkie pytanie")
        for _ in range(4):
            pytanie(t, "Częste pytanie")

        luki = luki_w_wiedzy(t)

        assert [p["pytanie"] for p in luki] == ["Częste pytanie", "Rzadkie pytanie"]

    def test_oryginalne_brzmienie_jest_zachowane(self):
        """Klient ma zobaczyć pytanie tak, jak je zadano — znormalizowana
        wersja służy tylko do sklejania."""
        t = firma()
        pytanie(t, "Czy MACIE parking?")

        assert luki_w_wiedzy(t)[0]["pytanie"] == "Czy MACIE parking?"

    def test_odpowiedzi_z_pokryciem_nie_sa_lukami(self):
        t = firma()
        pytanie(t, "Ile kosztuje sala?", source="document")
        pytanie(t, "Jakie są godziny?", source="faq")

        assert luki_w_wiedzy(t) == []

    def test_luki_innej_firmy_nie_wyciekaja(self):
        obca = firma()
        pytanie(obca, "Pytanie obcej firmy")
        moja = Tenant.objects.create(name="Moja", owner_email="ja@firma.pl")

        assert luki_w_wiedzy(moja) == []


@pytest.mark.django_db
class TestOknaCzasu:
    def test_pytanie_na_samej_granicy_wchodzi_do_raportu(self):
        """Wykryte przez test, który wyglądał na niestabilny: znacznik czasu
        wpisu i górna granica okna potrafią wypaść w tej samej mikrosekundzie,
        bo zegar systemowy ma grubszy takt niż `datetime`. Przy granicy
        otwartej pytanie zadane w chwili liczenia raportu przepadało."""
        t = firma()
        wpis = pytanie(t, "Pytanie na styku")
        chwila = PromptLog.objects.get(pk=wpis.pk).created_at

        luki = luki_w_wiedzy(t, od=chwila, do=chwila)

        assert [p["pytanie"] for p in luki] == ["Pytanie na styku"]

    def test_starsze_niz_tydzien_wypadaja(self):
        t = firma()
        pytanie(t, "Świeże pytanie", dni_temu=2)
        pytanie(t, "Stare pytanie", dni_temu=9)

        wyslij_raport(t)

        assert "Świeże pytanie" in mail.outbox[0].body
        assert "Stare pytanie" not in mail.outbox[0].body



@pytest.mark.django_db
class TestKiedyListWychodzi:
    def test_brak_luk_to_brak_listu(self):
        """Decyzja, nie przeoczenie: list „w tym tygodniu nic" przychodzący
        co poniedziałek uczy omijać nadawcę wzrokiem, a wtedy przepadają też
        te listy, w których coś jest."""
        t = firma()
        pytanie(t, "Ile kosztuje sala?", source="document")

        assert wyslij_raport(t) is False
        assert len(mail.outbox) == 0

    def test_wylaczony_raport_nie_wychodzi(self):
        t = firma(raport_tygodniowy=False)
        pytanie(t, "Czy robicie chrzciny?")

        assert wyslij_raport(t) is False
        assert len(mail.outbox) == 0

    def test_domyslnie_wlaczony(self):
        """Odwrotnie niż powiadomienie o rozmowie: jeden list na tydzień,
        wyłącznie gdy jest o czym pisać."""
        t = firma()

        assert t.raport_tygodniowy is True

    def test_brak_adresu_to_brak_listu(self):
        t = firma(owner_email="")
        pytanie(t, "Czy robicie chrzciny?")

        assert wyslij_raport(t) is False

    def test_awaria_poczty_nie_wysadza_zadania(self):
        t = firma()
        pytanie(t, "Czy robicie chrzciny?")

        with patch("django.core.mail.send_mail", side_effect=OSError("SMTP padło")):
            assert wyslij_raport(t) is False


@pytest.mark.django_db
class TestTresci:
    def test_list_zawiera_pytania_i_krotnosc(self):
        t = firma()
        for _ in range(3):
            pytanie(t, "Czy organizujecie chrzciny?")
        pytanie(t, "Czy jest parking?")

        wyslij_raport(t)
        tresc = mail.outbox[0].body

        assert "Czy organizujecie chrzciny?" in tresc
        assert "Czy jest parking?" in tresc
        assert "3×" in tresc

    def test_list_prowadzi_do_bazy_wiedzy(self):
        """Bez linku raport jest wyrzutem sumienia, nie zadaniem do zrobienia."""
        t = firma()
        pytanie(t, "Czy robicie chrzciny?")

        wyslij_raport(t)

        assert "/faq" in mail.outbox[0].body

    def test_temat_mowi_ile_i_czyje(self):
        t = firma()
        pytanie(t, "Czy robicie chrzciny?")

        wyslij_raport(t)

        assert "Dwór Weselny" in mail.outbox[0].subject
        assert mail.outbox[0].to == ["wlasciciel@firma.pl"]

    def test_list_mowi_jak_go_wylaczyc(self):
        t = firma()
        pytanie(t, "Czy robicie chrzciny?")

        wyslij_raport(t)

        assert "wyłączyć" in mail.outbox[0].body


@pytest.mark.django_db
class TestObchoduTygodniowego:
    def test_omija_firmy_bez_luk_i_bez_zgody(self):
        z_lukami = firma()
        pytanie(z_lukami, "Czy robicie chrzciny?")

        bez_luk = Tenant.objects.create(name="Cisza", owner_email="cisza@firma.pl")
        wylaczony = Tenant.objects.create(
            name="Wypisany", owner_email="w@firma.pl", raport_tygodniowy=False
        )
        pytanie(bez_luk, "Ile kosztuje?", source="faq")
        pytanie(wylaczony, "Czy robicie chrzciny?")

        assert wyslij_raporty_tygodniowe() == 1
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["wlasciciel@firma.pl"]

    def test_awaria_u_jednej_firmy_nie_zatrzymuje_obchodu(self):
        """Jedna zepsuta skrzynka nie może pozbawić raportu wszystkich
        pozostałych klientów."""
        pierwsza = firma()
        druga = Tenant.objects.create(name="Druga", owner_email="druga@firma.pl")
        pytanie(pierwsza, "Czy robicie chrzciny?")
        pytanie(druga, "Czy jest parking?")

        licznik = {"wywolan": 0}

        def czasem_pada(*args, **kwargs):
            licznik["wywolan"] += 1
            if licznik["wywolan"] == 1:
                raise OSError("SMTP padło")
            return 1

        with patch("django.core.mail.send_mail", side_effect=czasem_pada):
            wyslane = wyslij_raporty_tygodniowe()

        assert licznik["wywolan"] == 2, "obchód zatrzymał się na pierwszej awarii"
        assert wyslane == 1


@pytest.mark.django_db
class TestWylacznikaWPanelu:
    """
    List obiecuje wprost: „możesz go wyłączyć w panelu". Jeśli tego przełącznika
    nie ma albo nie działa, obietnica jest kłamstwem, a jedyną drogą wyjścia
    zostaje oznaczenie nadawcy jako spam — czyli utrata też tych powiadomień,
    które niosą zapytanie od klienta.
    """
    URL = "/api/widget-settings/mine/"

    def _panel(self, tenant):
        from rest_framework.test import APIClient

        from accounts.models import CustomUser

        wlasciciel = CustomUser.objects.create_user(
            username="wl", email="wl@firma.pl", password="x",
            tenant=tenant, role="owner",
        )
        klient = APIClient()
        klient.force_authenticate(user=wlasciciel)
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        return klient

    def test_panel_widzi_ustawienie(self):
        t = firma()

        odp = self._panel(t).get(self.URL)

        assert odp.status_code == 200
        assert odp.json()["raport_tygodniowy"] is True

    def test_da_sie_wylaczyc(self):
        t = firma()

        odp = self._panel(t).patch(self.URL, {"raport_tygodniowy": False}, format="json")

        assert odp.status_code == 200
        t.refresh_from_db()
        assert t.raport_tygodniowy is False

    def test_publiczny_endpoint_nie_zdradza_ustawienia(self):
        """Ten sam wymóg co przy powiadomieniu o rozmowie: publiczny branding
        odpowiada na sam klucz API, który stoi jawnie w kodzie strony klienta."""
        from rest_framework.test import APIClient

        t = firma()
        klient = APIClient()
        klient.credentials(HTTP_X_API_KEY=str(t.api_key))

        assert "raport_tygodniowy" not in klient.get("/api/widget-settings/").json()


@pytest.mark.django_db
class TestPulpituIRaportuNaJednymZrodle:
    """
    Pulpit i list muszą liczyć luki tak samo. Przy dwóch implementacjach
    zaczęłyby pokazywać co innego, a klient nie miałby jak rozstrzygnąć,
    które kłamie — i słusznie przestałby ufać obu.
    """

    def _pulpit(self, tenant):
        from rest_framework.test import APIClient

        from accounts.models import CustomUser

        uzytkownik = CustomUser.objects.create_user(
            username="wl", email="wl@firma.pl", password="x",
            tenant=tenant, role="owner",
        )
        klient = APIClient()
        klient.force_authenticate(user=uzytkownik)
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        return klient.get("/api/analytics/")

    def test_pulpit_sklada_powtorzenia_tak_jak_list(self):
        t = firma()
        for _ in range(4):
            pytanie(t, "Czy organizujecie chrzciny?")

        odp = self._pulpit(t)

        assert odp.status_code == 200
        luki = odp.json()["unanswered"]
        assert len(luki) == 1
        assert luki[0]["question"] == "Czy organizujecie chrzciny?"
        assert luki[0]["count"] == 4

    def test_pulpit_pomija_pytania_starsze_niz_okno(self):
        """Wcześniej brana była cała historia konta, więc na górze listy
        „szanse na poprawę" siedziały pytania sprzed pół roku."""
        t = firma()
        pytanie(t, "Świeże pytanie", dni_temu=3)
        pytanie(t, "Prehistoryczne pytanie", dni_temu=200)

        luki = self._pulpit(t).json()["unanswered"]

        assert [p["question"] for p in luki] == ["Świeże pytanie"]

    def test_pulpit_nie_pokazuje_luk_obcej_firmy(self):
        obca = firma()
        pytanie(obca, "Pytanie obcej firmy")
        moja = Tenant.objects.create(name="Moja", owner_email="ja@firma.pl")

        assert self._pulpit(moja).json()["unanswered"] == []
