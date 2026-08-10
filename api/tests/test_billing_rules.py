"""
Kiedy wiadomość jest płatna.

Do tej pory widoki naliczały bezwarunkowo: awaria modelu po naszej stronie
zjadała klientowi wiadomość z limitu, za który zapłacił, i zwracała mu w zamian
komunikat o błędzie. Wersja strumieniowa odejmowała limit jeszcze przed
rozpoczęciem strumienia, z uzasadnieniem, że później nie da się już odrzucić
żądania — ale to myliło dwie różne rzeczy. Limit egzekwuje SubscriptionMiddleware,
zanim widok się wykona; naliczanie może więc spokojnie poczekać na wynik.

Reguła: płacimy za treść od modelu. Urwany strumień też się liczy (odwiedzający
zobaczył odpowiedź, my zapłaciliśmy za tokeny), sama awaria — nie.
"""
import json
import uuid

import pytest
from rest_framework.test import APIClient

from chat.models import ChatMessage


def zapytaj(tenant, klient=None):
    return (klient or APIClient()).post(
        "/api/widget/chat/",
        {"message": "Jakie macie godziny?", "conversation_session_id": str(uuid.uuid4())},
        format="json", HTTP_X_API_KEY=str(tenant.api_key),
    )


@pytest.mark.django_db
class TestNaliczaniaBezStrumienia:
    def test_udana_odpowiedz_zuzywa_wiadomosc(self, tenant, subscribtion, mocker):
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "Czynne 9-17.", "tokens": 12},
        )
        przed = subscribtion.current_message_count

        assert zapytaj(tenant).status_code == 200

        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed + 1

    def test_awaria_modelu_nie_zuzywa_wiadomosci(self, tenant, subscribtion, mocker):
        """Sedno poprawki."""
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            side_effect=RuntimeError("OpenAI padło"),
        )
        przed = subscribtion.current_message_count

        response = zapytaj(tenant)

        assert response.status_code == 200
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed

    def test_odpowiedz_nie_zdradza_pola_rozliczeniowego(self, tenant, subscribtion, mocker):
        """`billable` to informacja dla widoku, nie dla widgetu."""
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "Czynne 9-17.", "tokens": 12},
        )

        assert "billable" not in zapytaj(tenant).json()

    def test_nieudana_odpowiedz_i_tak_zostaje_zapisana(self, tenant, subscribtion, mocker):
        """
        Brak naliczenia nie może oznaczać braku śladu — inaczej nie da się
        później sprawdzić, ile awarii zobaczyli odwiedzający.
        """
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            side_effect=RuntimeError("OpenAI padło"),
        )

        zapytaj(tenant)

        assert ChatMessage.objects.filter(sender="bot").exists()


def zdarzenia_strumienia(response):
    tresc = b"".join(response.streaming_content).decode()
    return [
        json.loads(linia[len("data: "):])
        for linia in tresc.splitlines()
        if linia.startswith("data: ")
    ]


@pytest.mark.django_db
class TestNaliczaniaStrumieniowego:
    URL = "/api/widget/chat/stream/"

    def wyslij(self, tenant):
        return APIClient().post(
            self.URL,
            {"message": "Jakie macie godziny?",
             "conversation_session_id": str(uuid.uuid4())},
            format="json", HTTP_X_API_KEY=str(tenant.api_key),
        )

    def test_udany_strumien_zuzywa_wiadomosc(self, tenant, subscribtion, mocker):
        mocker.patch(
            "api.utils.chat_engine.get_client",
            return_value=mocker.Mock(**{
                "chat.completions.create.return_value": [
                    mocker.Mock(usage=None, choices=[
                        mocker.Mock(delta=mocker.Mock(content="Czynne "))
                    ]),
                    mocker.Mock(usage=None, choices=[
                        mocker.Mock(delta=mocker.Mock(content="9-17."))
                    ]),
                ]
            }),
        )
        przed = subscribtion.current_message_count

        zdarzenia = zdarzenia_strumienia(self.wyslij(tenant))

        assert any(z["type"] == "done" for z in zdarzenia)
        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed + 1

    def test_awaria_strumienia_nie_zuzywa_wiadomosci(self, tenant, subscribtion, mocker):
        mocker.patch(
            "api.utils.chat_engine.get_client",
            return_value=mocker.Mock(**{
                "chat.completions.create.side_effect": RuntimeError("OpenAI padło")
            }),
        )
        przed = subscribtion.current_message_count

        zdarzenia_strumienia(self.wyslij(tenant))

        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed

    def test_limit_nie_schodzi_zanim_odpowiedz_powstanie(self, tenant, subscribtion, mocker):
        """
        Wcześniej licznik rósł już w widoku, przed pierwszym tokenem. Sprawdzamy
        to wprost: dopóki nikt nie konsumuje strumienia, nic nie jest naliczone.
        """
        mocker.patch(
            "api.utils.chat_engine.get_client",
            return_value=mocker.Mock(**{
                "chat.completions.create.return_value": [
                    mocker.Mock(usage=None, choices=[
                        mocker.Mock(delta=mocker.Mock(content="Czynne 9-17."))
                    ]),
                ]
            }),
        )
        przed = subscribtion.current_message_count

        response = self.wyslij(tenant)

        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed

        zdarzenia_strumienia(response)

        subscribtion.refresh_from_db()
        assert subscribtion.current_message_count == przed + 1
