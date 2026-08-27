"""
Powitanie i proponowane pytania w widgecie.

Widget otwierał się pustym oknem z samym polem tekstowym — nic nie podpowiadało,
o co można zapytać, więc odwiedzający najczęściej je zamykał. Pytania wpisuje się
w panelu jako zwykły tekst, po jednym w wierszu, i to parsowanie musi być odporne
na puste linie i spacje, bo pisze je człowiek, nie program.
"""

import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
class TestParsowaniePytan:
    def test_kazdy_wiersz_to_osobne_pytanie(self, tenant):
        tenant.widget_suggested_questions = "Godziny otwarcia?\nCennik?\nDojazd?"

        assert tenant.suggested_questions() == ["Godziny otwarcia?", "Cennik?", "Dojazd?"]

    def test_puste_wiersze_i_spacje_odpadaja(self, tenant):
        tenant.widget_suggested_questions = "  Godziny?  \n\n\n   \nCennik?\n"

        assert tenant.suggested_questions() == ["Godziny?", "Cennik?"]

    def test_pokazujemy_najwyzej_cztery(self, tenant):
        """Więcej propozycji zasłania samo okno rozmowy."""
        tenant.widget_suggested_questions = "\n".join(f"Pytanie {i}" for i in range(10))

        assert len(tenant.suggested_questions()) == 4

    def test_brak_pytan_daje_pusta_liste(self, tenant):
        tenant.widget_suggested_questions = ""

        assert tenant.suggested_questions() == []


@pytest.mark.django_db
def test_widget_dostaje_powitanie_i_pytania(tenant):
    tenant.widget_welcome_message = "Cześć! W czym mogę pomóc?"
    tenant.widget_suggested_questions = "Godziny otwarcia?\nCennik?"
    tenant.save()

    response = APIClient().get("/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key))

    assert response.status_code == 200
    data = response.json()
    assert data["widget_welcome_message"] == "Cześć! W czym mogę pomóc?"
    assert data["widget_suggested_questions"] == ["Godziny otwarcia?", "Cennik?"]


@pytest.mark.django_db
def test_wlasciciel_zapisuje_powitanie_z_panelu(user, tenant):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_API_KEY=str(tenant.api_key))

    response = client.patch(
        "/api/widget-settings/mine/",
        {
            "widget_welcome_message": "Dzień dobry!",
            "widget_suggested_questions": "Godziny?\nCennik?",
        },
        format="json",
    )

    assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.widget_welcome_message == "Dzień dobry!"
    assert tenant.suggested_questions() == ["Godziny?", "Cennik?"]
