"""
Powiadomienie firmy o nowym zapytaniu z czatu.

Zapytanie to najcenniejsza rzecz, jaką ten produkt wytwarza, i jedyna,
której klient nie zobaczy sam z siebie. Testujemy trzy rzeczy, które
wcześniej nie działały: czy w mailu jest przebieg rozmowy, czy wysyłka
nie blokuje odpowiedzi dla odwiedzającego i czy nieudana wysyłka zostawia
ślad zamiast ciszy.
"""
from unittest.mock import patch

import pytest
from django.core import mail
from rest_framework.test import APIClient

from accounts.models import Tenant
from chat.models import ChatMessage, ContactRequest, Conversation
from chat.powiadomienia import powiadom_o_zapytaniu, zapis_rozmowy


def firma(email="wlasciciel@firma.pl"):
    return Tenant.objects.create(name="Serwis Kowalski", owner_email=email)


def rozmowa_z_wymiana(tenant):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
    ChatMessage.objects.create(
        conversation=rozmowa, sender="user", message="Ile kosztuje przegląd roweru?"
    )
    ChatMessage.objects.create(
        conversation=rozmowa, sender="bot", message="Przegląd podstawowy to 120 zł."
    )
    ChatMessage.objects.create(
        conversation=rozmowa, sender="user", message="A czy robicie to na miejscu w sobotę?"
    )
    return rozmowa


def zapytanie(tenant, rozmowa=None, **kw):
    return ContactRequest.objects.create(
        tenant=tenant, conversation=rozmowa,
        contact=kw.pop("contact", "jan@firma.pl"), **kw,
    )


@pytest.mark.django_db
class TestTresci:
    def test_mail_zawiera_przebieg_rozmowy(self):
        """Sedno zmiany. Bez rozmowy właściciel dostaje numer telefonu i nie
        wie, o co pytający się pytał — a to decyduje, czy oddzwonić od razu."""
        t = firma()
        powiadom_o_zapytaniu(zapytanie(t, rozmowa_z_wymiana(t)).pk)

        assert len(mail.outbox) == 1
        tresc = mail.outbox[0].body
        assert "Ile kosztuje przegląd roweru?" in tresc
        assert "Przegląd podstawowy to 120 zł." in tresc
        assert "czy robicie to na miejscu w sobotę?" in tresc
        assert "Klient:" in tresc and "Chat:" in tresc

    def test_kontakt_i_link_do_panelu_sa_zawsze(self):
        t = firma()
        powiadom_o_zapytaniu(zapytanie(t, contact="500100200", name="Anna").pk)

        tresc = mail.outbox[0].body
        assert "500100200" in tresc
        assert "Anna" in tresc
        assert "/leads" in tresc

    def test_brak_rozmowy_to_informacja_nie_pusta_sekcja(self):
        """Kontakt można zostawić bez wcześniejszej wymiany zdań. Mail ma
        wtedy powiedzieć wprost, że rozmowy nie było."""
        t = firma()
        powiadom_o_zapytaniu(zapytanie(t).pk)

        assert "bez wcześniejszej rozmowy" in mail.outbox[0].body

    def test_kolejnosc_jest_zachowana_przy_identycznym_czasie(self):
        """Wykryte przez niestabilny test: wiadomości zapisane w tej samej
        chwili dawały remis w sortowaniu, a baza zwracała je wtedy w dowolnej
        kolejności. W mailu mogła wyjść odpowiedź przed pytaniem."""
        t = firma()
        rozmowa = Conversation.objects.create(tenant=t, user_identifier="gosc")
        for numer in range(6):
            ChatMessage.objects.create(
                conversation=rozmowa, sender="user", message=f"krok {numer}"
            )
        zapis = zapis_rozmowy(zapytanie(t, rozmowa))

        pozycje = [zapis.index(f"krok {n}") for n in range(6)]
        assert pozycje == sorted(pozycje), f"kolejność się rozjechała: {zapis}"

    def test_dlugie_rozmowy_sa_przycinane(self):
        """Cała rozmowa bywa długa; do decyzji wystarcza ostatni fragment."""
        t = firma()
        rozmowa = Conversation.objects.create(tenant=t, user_identifier="gosc")
        for numer in range(30):
            ChatMessage.objects.create(
                conversation=rozmowa, sender="user", message=f"pytanie numer {numer}"
            )
        zapis = zapis_rozmowy(zapytanie(t, rozmowa))

        assert zapis.count("\n") + 1 == 12
        # Zostaje KONIEC rozmowy, nie początek — tam jest to, na czym stanęło
        assert "pytanie numer 29" in zapis
        assert "pytanie numer 0\n" not in zapis


@pytest.mark.django_db
class TestSladu:
    def test_udana_wysylka_zostawia_znacznik(self):
        t = firma()
        z = zapytanie(t)
        powiadom_o_zapytaniu(z.pk)
        z.refresh_from_db()

        assert z.powiadomiono_at is not None
        assert z.blad_powiadomienia == ""

    def test_nieudana_wysylka_zapisuje_powod(self):
        """Wcześniej wysyłka miała fail_silently=True wewnątrz try/except.
        Zepsuta poczta oznaczała ciszę: klient nie dostawał maila i nie miał
        jak się dowiedzieć, że go nie dostał."""
        t = firma()
        z = zapytanie(t)

        with patch("chat.powiadomienia.send_mail", side_effect=OSError("SMTP nie odpowiada")):
            powiadom_o_zapytaniu(z.pk)
        z.refresh_from_db()

        assert z.powiadomiono_at is None
        assert "OSError" in z.blad_powiadomienia
        assert "SMTP nie odpowiada" in z.blad_powiadomienia

    def test_brak_adresu_wlasciciela_tez_jest_zapisany(self):
        """Firma bez adresu e-mail nie dostanie powiadomienia nigdy —
        to musi być widoczne, a nie ciche."""
        t = firma(email="")
        z = zapytanie(t)
        powiadom_o_zapytaniu(z.pk)
        z.refresh_from_db()

        assert len(mail.outbox) == 0
        assert z.powiadomiono_at is None
        assert z.blad_powiadomienia.startswith("BRAK_ADRESU")

    def test_awaria_wysylki_ma_inny_znacznik_niz_brak_adresu(self):
        """Panel podpowiada co innego przy każdej z tych przyczyn, więc muszą
        być rozróżnialne. Wcześniej obie dostawały ten sam komunikat i przy
        zepsutej skrzynce nadawczej rada brzmiała „sprawdź adres w ustawieniach
        konta" — czyli wysyłała do grzebania w niewłaściwym miejscu."""
        t = firma()
        z = zapytanie(t)

        with patch("chat.powiadomienia.send_mail",
                   side_effect=OSError("SMTPAuthenticationError: 535")):
            powiadom_o_zapytaniu(z.pk)
        z.refresh_from_db()

        assert not z.blad_powiadomienia.startswith("BRAK_ADRESU")
        assert "535" in z.blad_powiadomienia

    def test_awaria_poczty_nie_gubi_samego_zapytania(self):
        """Zapytanie jest cenniejsze niż powiadomienie o nim."""
        t = firma()
        z = zapytanie(t)

        with patch("chat.powiadomienia.send_mail", side_effect=OSError("padło")):
            powiadom_o_zapytaniu(z.pk)

        assert ContactRequest.objects.filter(pk=z.pk).exists()


@pytest.mark.django_db
class TestSciezkiZWidgetu:
    def test_odwiedzajacy_dostaje_odpowiedz_nie_czekajac_na_poczte(self):
        """Wysyłka szła wewnątrz widoku, więc odwiedzający czekał na serwer
        poczty w najgorszym możliwym momencie — tuż po zostawieniu numeru."""
        t = firma()
        rozmowa = rozmowa_z_wymiana(t)
        klient = APIClient()
        klient.credentials(HTTP_X_API_KEY=str(t.api_key))

        with patch("api.views.contact.enqueue") as zlecenie:
            odp = klient.post("/api/widget/contact/", {
                "contact": "jan@firma.pl",
                "conversation_session_id": str(rozmowa.session_id),
            }, format="json")

        assert odp.status_code == 201
        # Widok zleca zadanie, a nie wysyła maila sam
        assert zlecenie.called
        assert len(mail.outbox) == 0

    def test_zapytanie_z_widgetu_dociera_do_maila_z_rozmowa(self):
        """Pełna ścieżka: widget → zapytanie → powiadomienie z kontekstem."""
        t = firma()
        rozmowa = rozmowa_z_wymiana(t)
        klient = APIClient()
        klient.credentials(HTTP_X_API_KEY=str(t.api_key))

        odp = klient.post("/api/widget/contact/", {
            "contact": "jan@firma.pl",
            "conversation_session_id": str(rozmowa.session_id),
        }, format="json")

        assert odp.status_code == 201
        assert len(mail.outbox) == 1
        assert "Ile kosztuje przegląd roweru?" in mail.outbox[0].body
        assert mail.outbox[0].to == ["wlasciciel@firma.pl"]
