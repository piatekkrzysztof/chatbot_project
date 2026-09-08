"""
Parametry wywołania modelu.

Kategoria ryzyka: AWARIA CAŁEGO CZATU, BEZ ALERTU.

Nowsze modele OpenAI (od gpt-5.x) odrzucają `max_tokens` i odrzucają
`temperature` inną niż domyślna - błędem 400, przy każdym pytaniu. A
`process_chat_message` łapie wyjątek i oddaje komunikat awaryjny, więc bot
odpowiadałby „coś poszło nie tak" wszystkim klientom naraz.

Co gorsza, nic by tego nie zgłosiło: fragmenty z wyszukiwania wracają
normalnie, więc `determine_source` zapisuje źródło „document", alert o
odmowach nie widzi wzrostu, a alert o ciszy nie widzi ciszy - rozmowy przecież
są. Wykryłby to dopiero klient.

Znalezione przy pierwszej próbie uruchomienia gpt-5.6-luna, 8 września 2026.
Nie w przeglądzie kodu - przy uruchomieniu.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from api.utils.chat_engine import parametry_modelu


class TestZgodnosciZNowymiModelami:
    def test_uzywa_max_completion_tokens_a_nie_max_tokens(self):
        """
        `max_completion_tokens` rozumieją wszystkie modele, `max_tokens` tylko
        starsze. Nowa nazwa działa więc wszędzie i nie ma powodu trzymać starej.
        """
        parametry = parametry_modelu()

        assert "max_completion_tokens" in parametry
        assert "max_tokens" not in parametry

    @override_settings(OPENAI_TEMPERATURE=None)
    def test_pusta_temperatura_nie_jest_wysylana(self):
        """
        Nie „wysyłamy 1.0", tylko NIE WYSYŁAMY PARAMETRU.

        gpt-5.6-luna odrzuca każdą jawną wartość, także tę, którą sam ma
        domyślnie. Wysłanie `temperature=1.0` jest więc równie złe jak 0.2.
        """
        assert "temperature" not in parametry_modelu()

    @override_settings(OPENAI_TEMPERATURE=0.2)
    def test_ustawiona_temperatura_jest_wysylana(self):
        # Druga strona. Gdyby parametr znikal zawsze, model zaczalby zmyslac
        # przy pustym kontekscie - a od tego byla ta wartosc.
        assert parametry_modelu()["temperature"] == 0.2

    def test_mozna_nadpisac_temperature_na_jedno_wywolanie(self):
        # Do porownywania modeli przy wspolnym ustawieniu: model, ktory nie
        # przyjmuje 0.2, i model, ktory przyjmuje, musza byc zmierzone na tej
        # samej temperaturze, inaczej porownanie mierzy dwie rozne rzeczy.
        assert "temperature" not in parametry_modelu(temperatura=None)


@pytest.mark.django_db
class TestObuSciezekCzatu:
    """
    Ścieżki są dwie: zwykła i strumieniowa. Rozjazd między nimi znaczy, że
    czat działa, a strumień pada - albo odwrotnie, zależnie od tego, którą
    drogą poszło zapytanie. Widget używa strumieniowej.
    """

    def _parametry_wywolania(self, klient):
        return klient.chat.completions.create.call_args.kwargs

    def test_sciezka_zwykla_nie_wysyla_max_tokens(self):
        from api.utils.chat_engine import get_openai_response

        klient = MagicMock()
        klient.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))],
            usage=MagicMock(total_tokens=5),
        )

        with patch("api.utils.chat_engine.get_client", return_value=klient):
            get_openai_response([{"role": "user", "content": "test"}])

        uzyte = self._parametry_wywolania(klient)
        assert "max_tokens" not in uzyte
        assert uzyte["max_completion_tokens"]

    def test_sciezka_strumieniowa_nie_wysyla_max_tokens(self):
        from accounts.models import Tenant
        from api.utils.chat_engine import stream_chat_message
        from chat.models import Conversation

        firma = Tenant.objects.create(name="Firma od parametrow")
        rozmowa = Conversation.objects.create(tenant=firma, user_identifier="test")

        klient = MagicMock()
        klient.chat.completions.create.return_value = iter([])

        with patch("api.utils.chat_engine.get_client", return_value=klient):
            list(stream_chat_message(firma, rozmowa, "test"))

        uzyte = self._parametry_wywolania(klient)
        assert "max_tokens" not in uzyte
        assert uzyte["max_completion_tokens"]

    @override_settings(OPENAI_TEMPERATURE=None)
    def test_obie_sciezki_pomijaja_pusta_temperature(self):
        from accounts.models import Tenant
        from api.utils.chat_engine import get_openai_response, stream_chat_message
        from chat.models import Conversation

        firma = Tenant.objects.create(name="Firma od temperatury")
        rozmowa = Conversation.objects.create(tenant=firma, user_identifier="test")

        klient = MagicMock()
        klient.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))],
            usage=MagicMock(total_tokens=5),
        )
        with patch("api.utils.chat_engine.get_client", return_value=klient):
            get_openai_response([{"role": "user", "content": "test"}])
            assert "temperature" not in self._parametry_wywolania(klient)

            klient.chat.completions.create.return_value = iter([])
            list(stream_chat_message(firma, rozmowa, "test"))
            assert "temperature" not in self._parametry_wywolania(klient)
