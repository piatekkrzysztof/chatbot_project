"""
Pusta odpowiedź modelu - 2.28.0.

Kategoria ryzyka: CISZA ZAMIAST ODPOWIEDZI, BEZ ŚLADU. Od 8.10.2026 produkcja
działa na gpt-6-luna z rozumowaniem, które liczy się do limitu tokenów
wyjścia. Gdy myślenie zje limit, odpowiedź przychodzi pusta, z poprawnym
kodem HTTP. W pomiarze gpt-5-nano robił tak w 24 z 35 pytań.

Do 2.28.0: widget pokazywał pusty dymek i nikt się nie dowiadywał, a ścieżka
bez strumienia najpierw naliczała wiadomość z limitu klienta, potem padała na
pustej treści. Pusta odpowiedź ma iść drogą awarii: komunikat, bez naliczenia,
z wpisem w logu.
"""

import json
import logging
import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from api.tests.test_widget_chat_stream import make_openai_stream
from api.utils.chat_engine import FALLBACK_MESSAGE, stream_chat_message
from chat.lifecycle import usun_rozmowe
from chat.models import ChatMessage, Conversation

pytestmark = pytest.mark.django_db


def zdarzenia(response):
    tresc = b"".join(response.streaming_content).decode()
    return [
        json.loads(linia[len("data: ") :])
        for linia in tresc.splitlines()
        if linia.startswith("data: ")
    ]


def strumien_modelu(mocker, kawalki):
    """Zdarzenia strumienia OpenAI: treść po kawałku, na końcu licznik tokenów."""
    zdarzenia_modelu = [
        mocker.Mock(usage=None, choices=[mocker.Mock(delta=mocker.Mock(content=k))])
        for k in kawalki
    ]
    koniec = mocker.Mock(choices=[])
    koniec.usage.total_tokens = 640
    koniec.usage.prompt_tokens = 40
    koniec.usage.completion_tokens = 600
    zdarzenia_modelu.append(koniec)
    mocker.patch(
        "api.utils.chat_engine.get_client",
        return_value=mocker.Mock(**{"chat.completions.create.return_value": zdarzenia_modelu}),
    )


def wyslij_strumien(tenant):
    return APIClient().post(
        "/api/widget/chat/stream/",
        {"message": "Jakie macie godziny?", "conversation_session_id": str(uuid.uuid4())},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )


def wyslij_bez_strumienia(tenant):
    return APIClient().post(
        "/api/widget/chat/",
        {"message": "Jakie macie godziny?", "conversation_session_id": str(uuid.uuid4())},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )


class TestStrumien:
    def test_pusty_strumien_daje_komunikat_zamiast_pustego_dymka(
        self, tenant, subscribtion, mocker, caplog
    ):
        """Ten test padał przed 2.28.0: widget dostawał „done" bez żadnej treści."""
        strumien_modelu(mocker, [])
        przed = subscribtion.current_message_count

        with caplog.at_level(logging.ERROR, logger="api.utils.chat_engine"):
            wynik = zdarzenia(wyslij_strumien(tenant))

        tresc = "".join(z["content"] for z in wynik if z["type"] == "delta")
        assert tresc == FALLBACK_MESSAGE
        assert any(z["type"] == "done" for z in wynik)
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed
        assert "Pusta odpowiedź modelu" in caplog.text

    def test_krotka_odpowiedz_z_bufora_nie_jest_pusta(self, tenant, subscribtion, mocker):
        """„OK" siedzi w buforze znacznika do końca strumienia - to nie pusta odpowiedź."""
        strumien_modelu(mocker, ["OK"])

        wynik = zdarzenia(wyslij_strumien(tenant))

        tresc = "".join(z["content"] for z in wynik if z["type"] == "delta")
        assert tresc == "OK"

    def test_same_biale_znaki_to_tez_pusta_odpowiedz(self, tenant, subscribtion, mocker):
        """Spacje i nowe linie to nie odpowiedź - ani do pokazania, ani do naliczenia."""
        # Dłużej niż znacznik [BRAK_ODPOWIEDZI]: krótsze spacje zatrzymuje jego
        # bufor, a te mają przejść przez pętlę strumienia.
        strumien_modelu(mocker, [" " * 30, "\n" * 5, " " * 30])
        przed = subscribtion.current_message_count

        wynik = zdarzenia(wyslij_strumien(tenant))

        assert FALLBACK_MESSAGE in "".join(z["content"] for z in wynik if z["type"] == "delta")
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed

    def test_odpowiedz_po_bialych_znakach_jest_naliczona(self, tenant, subscribtion, mocker):
        """Druga strona: treść po początkowej spacji to normalna, płatna odpowiedź."""
        strumien_modelu(mocker, [" ", "Czynne 9-17, w soboty 10-14."])
        przed = subscribtion.current_message_count

        wynik = zdarzenia(wyslij_strumien(tenant))

        assert FALLBACK_MESSAGE not in "".join(z["content"] for z in wynik if z["type"] == "delta")
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed + 1


class TestBezStrumienia:
    @pytest.mark.parametrize("tresc", [None, "", "   \n"])
    def test_pusta_tresc_nie_nalicza_i_nie_wywraca(self, tenant, subscribtion, mocker, tresc):
        """Ten test padał przed 2.28.0: wiadomość naliczona, potem błąd na None."""
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": tresc, "tokens": 640, "tokeny_wyjscia": 600},
        )
        przed = subscribtion.current_message_count

        odpowiedz = wyslij_bez_strumienia(tenant)

        assert odpowiedz.status_code == 200
        assert odpowiedz.json()["response"] == FALLBACK_MESSAGE
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed
        assert ChatMessage.objects.filter(sender="bot", message=FALLBACK_MESSAGE).exists()


def test_rozmowa_usunieta_przed_pierwszym_slowem_to_nie_pusta_odpowiedz(tenant, caplog):
    """
    Usunięcie, zanim model cokolwiek napisał, też zostawia zero treści - ale to
    nie awaria modelu. Bez tego wyjątku odwiedzający zobaczyłby na chwilę
    komunikat o błędzie przed informacją o usunięciu, a log - fałszywy alarm.
    """
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="test")

    class Model:
        def __iter__(self):
            usun_rozmowe(tenant, rozmowa.session_id)
            yield make_openai_stream(["za późno"])[0]

        def close(self):
            pass

    with (
        patch("api.utils.chat_engine.get_client") as klient,
        patch("api.utils.chat_engine.build_chat_messages", return_value=([], [], [], False)),
        patch("api.utils.chat_engine.time.monotonic", side_effect=[0, 1, 2]),
        caplog.at_level(logging.ERROR, logger="api.utils.chat_engine"),
    ):
        klient.return_value.chat.completions.create.return_value = Model()
        wynik = [json.loads(s[6:]) for s in stream_chat_message(tenant, rozmowa, "pytanie")]

    assert [z["type"] for z in wynik] == ["error"]
    assert wynik[0]["code"] == "conversation_deleted"
    assert "Pusta odpowiedź modelu" not in caplog.text
