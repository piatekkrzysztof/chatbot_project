"""
Wiadomość proaktywna — zaczepka pokazywana, zanim odwiedzający cokolwiek napisze.

Dwie rzeczy odróżniają ją od zwykłej odpowiedzi bota i obie są tu sprawdzane.
Po pierwsze, to gotowy tekst klienta, nie odpowiedź modelu — nie wolno jej
liczyć do limitu planu ani wywoływać OpenAI. Po drugie, języka nie da się wykryć
z wiadomości, bo wiadomości jeszcze nie ma; bierzemy go z wersji językowej
strony klienta, którą embed.js czyta z atrybutu <html lang>.
"""
import pytest
from rest_framework.test import APIClient

from accounts.models import Tenant


class TestWyboruWersjiJezykowej:
    def test_dokladne_dopasowanie(self):
        tenant = Tenant(
            widget_default_language="pl",
            widget_proactive_texts={"pl": "Pomóc?", "en": "Need help?"},
        )

        assert tenant.proactive_text_for("en") == "Need help?"

    def test_kod_regionalny_sprowadzamy_do_jezyka(self):
        """Atrybut lang bywa pełny — "en-GB" ma trafić na wersję angielską."""
        tenant = Tenant(
            widget_default_language="pl",
            widget_proactive_texts={"pl": "Pomóc?", "en": "Need help?"},
        )

        assert tenant.proactive_text_for("en-GB") == "Need help?"
        assert tenant.proactive_text_for("EN_us") == "Need help?"

    def test_brak_wersji_schodzi_na_domyslna(self):
        """Strona po niemiecku, klient nie napisał wersji niemieckiej."""
        tenant = Tenant(
            widget_default_language="pl",
            widget_proactive_texts={"pl": "Pomóc?", "en": "Need help?"},
        )

        assert tenant.proactive_text_for("de") == "Pomóc?"

    def test_brak_domyslnej_bierze_cokolwiek(self):
        """
        Klient ustawił domyślny polski, ale wypełnił tylko angielski. Lepiej
        pokazać zaczepkę po angielsku niż nie pokazać jej wcale.
        """
        tenant = Tenant(
            widget_default_language="pl",
            widget_proactive_texts={"en": "Need help?"},
        )

        assert tenant.proactive_text_for("de") == "Need help?"

    def test_brak_tekstow_to_brak_zaczepki(self):
        assert Tenant(widget_proactive_texts={}).proactive_text_for("pl") == ""

    @pytest.mark.parametrize("smiec", [None, [], "tekst", 42])
    def test_uszkodzona_konfiguracja_nie_wywraca_widgetu(self, smiec):
        """JSONField przyjmie każdy kształt — widget nie może się na tym wyłożyć."""
        assert Tenant(widget_proactive_texts=smiec).proactive_text_for("pl") == ""

    def test_puste_i_nieznane_jezyki_odpadaja(self):
        tenant = Tenant(
            widget_default_language="pl",
            widget_proactive_texts={"pl": "  ", "klingoński": "nuqneH", "en": " Hi "},
        )

        assert tenant.proactive_texts() == {"en": "Hi"}


@pytest.mark.django_db
class TestZaczepkiWApiWidgetu:
    def test_widget_dostaje_wersje_dla_jezyka_strony(self, tenant):
        tenant.widget_proactive_enabled = True
        tenant.widget_proactive_texts = {"pl": "Pomóc?", "en": "Need help?"}
        tenant.save()

        dane = APIClient().get(
            "/api/widget-settings/?lang=en-GB", HTTP_X_API_KEY=str(tenant.api_key)
        ).json()

        assert dane["widget_proactive_enabled"] is True
        assert dane["widget_proactive_text"] == "Need help?"

    def test_bez_parametru_lang_dostajemy_domyslna(self, tenant):
        tenant.widget_proactive_enabled = True
        tenant.widget_default_language = "pl"
        tenant.widget_proactive_texts = {"pl": "Pomóc?", "en": "Need help?"}
        tenant.save()

        dane = APIClient().get(
            "/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key)
        ).json()

        assert dane["widget_proactive_text"] == "Pomóc?"

    def test_wlasciciel_zapisuje_zaczepke(self, user, tenant):
        user.tenant = tenant
        user.role = "owner"
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        response = client.patch(
            "/api/widget-settings/mine/",
            {
                "widget_proactive_enabled": True,
                "widget_proactive_delay_seconds": 15,
                "widget_proactive_texts": {"pl": "Pomóc?", "en": "Need help?"},
            },
            format="json",
        )

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.widget_proactive_enabled is True
        assert tenant.widget_proactive_delay_seconds == 15
        assert tenant.proactive_texts() == {"pl": "Pomóc?", "en": "Need help?"}

    def test_teksty_moga_przyjsc_jako_json_w_formularzu(self, user, tenant):
        """Panel wysyła multipart, bo w tym samym żądaniu lecą logo i awatar."""
        user.tenant = tenant
        user.role = "owner"
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        response = client.patch(
            "/api/widget-settings/mine/",
            {"widget_proactive_texts": '{"pl": "Pomóc?"}'},
            format="multipart",
        )

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.proactive_texts() == {"pl": "Pomóc?"}

    def test_uszkodzony_json_daje_czytelny_blad(self, user, tenant):
        user.tenant = tenant
        user.role = "owner"
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        response = client.patch(
            "/api/widget-settings/mine/",
            {"widget_proactive_texts": "{niepoprawny"},
            format="multipart",
        )

        assert response.status_code == 400
