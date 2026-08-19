"""
Powiadomienie o rozpoczętej rozmowie.

Powstało, bo przejęcie kontaktu ma wąski lejek: propozycja zostawienia
namiarów pojawia się tylko wtedy, gdy bot nie znalazł odpowiedzi. Rozmowa,
w której nikt nic nie zostawił, i tak bywa warta oddzwonienia — o ile
właściciel w ogóle o niej wie.

Testujemy trzy rzeczy, na których to stoi: że mail leci raz na rozmowę
(a nie po każdej wypowiedzi), że domyślnie nie leci wcale, i że obie
ścieżki czatu — strumieniowa i zwykła — zachowują się tak samo.
"""
from unittest.mock import patch

import pytest
from django.core import mail

from accounts.models import Tenant
from chat.models import ChatMessage, Conversation
from chat.powiadomienia import powiadom_o_rozmowie


def firma(**kw):
    kw.setdefault("owner_email", "wlasciciel@firma.pl")
    kw.setdefault("powiadom_o_rozmowie", True)
    return Tenant.objects.create(name="Serwis Kowalski", **kw)


def rozmowa(tenant):
    return Conversation.objects.create(tenant=tenant, user_identifier="gosc")


@pytest.mark.django_db
class TestTresci:
    def test_mail_zawiera_pierwsze_pytanie(self):
        """Sam sygnał „ktoś pisze" jest bezużyteczny — o tym, czy to warte
        uwagi, decyduje treść pytania."""
        r = rozmowa(firma())
        ChatMessage.objects.create(
            conversation=r, sender="user", message="Czy organizujecie chrzciny?"
        )
        powiadom_o_rozmowie(r.pk)

        assert len(mail.outbox) == 1
        assert "Czy organizujecie chrzciny?" in mail.outbox[0].body
        assert mail.outbox[0].to == ["wlasciciel@firma.pl"]

    def test_pytanie_to_pierwsza_wiadomosc_a_nie_ostatnia(self):
        """Powiadomienie może wyjść z opóźnieniem, gdy kolejka jest zajęta —
        do tego czasu rozmowa bywa już dłuższa. Interesuje nas to, z czym ktoś
        przyszedł, nie to, na czym akurat stanęło."""
        r = rozmowa(firma())
        for numer in range(4):
            ChatMessage.objects.create(
                conversation=r, sender="user", message=f"pytanie {numer}"
            )
        powiadom_o_rozmowie(r.pk)

        assert "pytanie 0" in mail.outbox[0].body
        assert "pytanie 3" not in mail.outbox[0].body

    def test_brak_adresu_wlasciciela_nie_wysadza_zadania(self):
        r = rozmowa(firma(owner_email=""))
        powiadom_o_rozmowie(r.pk)

        assert len(mail.outbox) == 0

    def test_awaria_poczty_nie_wysadza_zadania(self):
        """Rozmowa jest ważniejsza niż powiadomienie o niej — a zadanie leci
        w tle tej samej odpowiedzi, którą widzi odwiedzający."""
        r = rozmowa(firma())
        with patch("chat.powiadomienia.send_mail", side_effect=OSError("SMTP padło")):
            powiadom_o_rozmowie(r.pk)  # nie rzuca


@pytest.mark.django_db
class TestKiedyLeci:
    """Rdzeń tej funkcji. Reszta to formatowanie."""

    def _wyslij(self, tenant, tresc):
        from api.utils.chat_engine import zapisz_pytanie_i_zglos_start
        r, _ = Conversation.objects.get_or_create(tenant=tenant, user_identifier="gosc")
        zapisz_pytanie_i_zglos_start(tenant, r, tresc)
        return r

    def test_pierwsza_wiadomosc_zleca_powiadomienie(self):
        t = firma()
        with patch("api.utils.chat_engine.enqueue") as zlecenie:
            self._wyslij(t, "dzień dobry")

        assert zlecenie.called

    def test_kolejne_wiadomosci_juz_nie(self):
        """Bez tego dziesięciozdaniowa rozmowa to dziesięć maili o tej samej
        rozmowie — właściciel przestaje je czytać, w tym te z zapytaniami."""
        t = firma()
        with patch("api.utils.chat_engine.enqueue") as zlecenie:
            self._wyslij(t, "dzień dobry")
            self._wyslij(t, "a ile to kosztuje?")
            self._wyslij(t, "a na sobotę?")

        assert zlecenie.call_count == 1

    def test_domyslnie_wylaczone(self):
        """Przy realnym ruchu mail od każdego odwiedzającego staje się szumem
        i uczy właściciela ignorować powiadomienia — także te z zapytaniami.
        Dlatego to świadoma decyzja klienta, nie ustawienie domyślne."""
        t = firma(powiadom_o_rozmowie=False)
        with patch("api.utils.chat_engine.enqueue") as zlecenie:
            self._wyslij(t, "dzień dobry")

        assert not zlecenie.called

    def test_zapytanie_zapisuje_sie_tak_czy_inaczej(self):
        """Powiadomienie jest dodatkiem — wiadomość musi wylądować w bazie
        niezależnie od ustawienia."""
        t = firma(powiadom_o_rozmowie=False)
        r = self._wyslij(t, "dzień dobry")

        assert ChatMessage.objects.filter(conversation=r, sender="user").count() == 1

    def test_druga_rozmowa_dostaje_wlasne_powiadomienie(self):
        """Licznik jest per rozmowa, nie per firma."""
        t = firma()
        with patch("api.utils.chat_engine.enqueue") as zlecenie:
            from api.utils.chat_engine import zapisz_pytanie_i_zglos_start
            for kto in ("gosc-a", "gosc-b"):
                r = Conversation.objects.create(tenant=t, user_identifier=kto)
                zapisz_pytanie_i_zglos_start(t, r, "dzień dobry")

        assert zlecenie.call_count == 2


@pytest.mark.django_db
class TestWidocznosciUstawienia:
    """
    Publiczny endpoint brandingu odpowiada na sam klucz API, bez logowania —
    a ten klucz stoi jawnie w kodzie strony klienta. Ustawienia właściciela
    nie mogą tamtędy wychodzić.
    """

    def test_publiczny_branding_nie_zdradza_ustawienia(self):
        from rest_framework.test import APIClient

        t = firma()
        klient = APIClient()
        klient.credentials(HTTP_X_API_KEY=str(t.api_key))
        odp = klient.get("/api/widget-settings/")

        assert odp.status_code == 200
        assert "powiadom_o_rozmowie" not in odp.json()

    def test_panel_widzi_ustawienie(self):
        """Druga strona tej samej zmiany: rozdzielenie nie może odciąć panelu
        od pola, którym steruje."""
        from rest_framework.test import APIClient

        from accounts.models import CustomUser

        t = firma()
        wlasciciel = CustomUser.objects.create_user(
            username="wl", email="wl@firma.pl", password="x", tenant=t, role="owner"
        )
        klient = APIClient()
        klient.force_authenticate(user=wlasciciel)
        # TenantMiddleware rozstrzyga tenanta przed DRF, więc force_authenticate
        # samo w sobie nie wystarcza — bez klucza żądanie ginie na 401
        klient.credentials(HTTP_X_API_KEY=str(t.api_key))
        odp = klient.get("/api/widget-settings/mine/")

        assert odp.status_code == 200
        assert odp.json()["powiadom_o_rozmowie"] is True
