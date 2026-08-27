"""
Ocena odpowiedzi kciukiem z poziomu widgetu.

Endpoint oceny istniał od dawna, ale wymagał tokenu JWT — czyli mógł go wywołać
wyłącznie zalogowany właściciel, nigdy odwiedzający stronę klienta. Kciuków
w oknie czatu nie było, a badanie rynku wymienia CSAT jako standard u liderów.

Przy okazji wyszedł poważniejszy problem: serializer szukał wiadomości wśród
wszystkich firm. Dopóki chronił go JWT, ryzyko było ograniczone — ale otwarcie
tego dla widgetu zrobiłoby z tego zapis między tenantami.
"""

import uuid

import pytest
from rest_framework.test import APIClient

from chat.models import ChatFeedback, ChatMessage, Conversation


def wiadomosc_bota(tenant, tresc="Odpowiedź"):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="10.0.0.0")
    return ChatMessage.objects.create(conversation=rozmowa, sender="bot", message=tresc)


@pytest.mark.django_db
class TestOcenaZWidgetu:
    URL = "/api/widget/feedback/"

    def test_odwiedzajacy_ocenia_bez_logowania(self, tenant):
        wiadomosc = wiadomosc_bota(tenant)

        response = APIClient().post(
            self.URL,
            {"message_id": wiadomosc.id, "is_helpful": True},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

        assert response.status_code == 200
        assert ChatFeedback.objects.get(message=wiadomosc).is_helpful is True

    def test_ponowna_ocena_nadpisuje_poprzednia(self, tenant):
        """Odwiedzający może się rozmyślić — nie tworzymy drugiego wpisu."""
        wiadomosc = wiadomosc_bota(tenant)
        klient = APIClient()
        naglowki = {"HTTP_X_API_KEY": str(tenant.api_key)}

        klient.post(
            self.URL, {"message_id": wiadomosc.id, "is_helpful": True}, format="json", **naglowki
        )
        klient.post(
            self.URL, {"message_id": wiadomosc.id, "is_helpful": False}, format="json", **naglowki
        )

        assert ChatFeedback.objects.filter(message=wiadomosc).count() == 1
        assert ChatFeedback.objects.get(message=wiadomosc).is_helpful is False

    def test_nie_da_sie_ocenic_rozmowy_innej_firmy(self, tenant):
        """
        Sedno poprawki. Wcześniej wystarczył sam identyfikator wiadomości,
        bez względu na to, do kogo należała.
        """
        from .factories import TenantFactory

        obcy = TenantFactory()
        cudza = wiadomosc_bota(obcy, "Cudza odpowiedź")

        response = APIClient().post(
            self.URL,
            {"message_id": cudza.id, "is_helpful": True},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

        assert response.status_code == 400
        assert not ChatFeedback.objects.filter(message=cudza).exists()

    def test_bez_klucza_api_odmowa(self, tenant):
        wiadomosc = wiadomosc_bota(tenant)

        response = APIClient().post(
            self.URL, {"message_id": wiadomosc.id, "is_helpful": True}, format="json"
        )

        assert response.status_code in (401, 403)
        assert not ChatFeedback.objects.filter(message=wiadomosc).exists()

    def test_nie_da_sie_ocenic_wlasnej_wiadomosci_uzytkownika(self, tenant):
        """Ocenia się odpowiedzi bota, nie pytania odwiedzającego."""
        rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="10.0.0.0")
        pytanie = ChatMessage.objects.create(conversation=rozmowa, sender="user", message="Pytanie")

        response = APIClient().post(
            self.URL,
            {"message_id": pytanie.id, "is_helpful": True},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

        assert response.status_code == 400


@pytest.mark.django_db
def test_czat_zwraca_identyfikator_odpowiedzi(tenant, subscribtion, mocker):
    """
    Bez tego identyfikatora widget nie ma czego ocenić — kciuki nie mają
    do czego się odnieść.
    """
    mocker.patch(
        "api.utils.chat_engine.get_openai_response",
        return_value={"content": "Odpowiedź", "tokens": 5},
    )

    response = APIClient().post(
        "/api/widget/chat/",
        {"message": "Pytanie", "conversation_session_id": str(uuid.uuid4())},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 200
    identyfikator = response.json()["message_id"]
    zapisana = ChatMessage.objects.get(id=identyfikator)
    assert zapisana.sender == "bot"
    assert zapisana.message == "Odpowiedź"
