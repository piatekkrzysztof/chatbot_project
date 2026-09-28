"""
Rozbicie tokenów trafia do logu, a nie tylko do sumy.

Kategoria ryzyka: PRZYRZĄD, KTÓRY KŁAMIE. Do 2.14.0 log zapisywał wyłącznie
`usage.total_tokens`, więc kosztu nie dało się policzyć - tylko oszacować
z długości promptu i odpowiedzi. Szacunek okazał się mierzyć co innego, niż
deklarował: `prompt` w logu to pytanie odwiedzającego, a nie prompt wysłany do
modelu. Kontekstu z bazy wiedzy, który stanowi większość wejścia, w logu nie ma
w ogóle, więc porównanie pytania z odpowiedzią zawyżało udział wyjścia - czyli
tej części, która kosztuje czterokrotnie drożej.

OpenAI zwraca `prompt_tokens` i `completion_tokens` w tej samej odpowiedzi,
z której braliśmy sumę. Te testy pilnują, że obie liczby faktycznie lądują
w bazie: bez nich poprawka wyglądałaby na zrobioną, a pomiar dalej by zgadywał.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.utils.chat_engine import process_chat_message
from chat.models import PromptLog

pytestmark = pytest.mark.django_db


def odpowiedz_modelu(wejscia, wyjscia):
    return {
        "content": "Odpowiedź bota.",
        "tokens": wejscia + wyjscia,
        "tokeny_wejscia": wejscia,
        "tokeny_wyjscia": wyjscia,
    }


@patch("api.utils.chat_engine.get_openai_response")
def test_rozbicie_ladu_je_w_logu(mock_gpt, tenant, conversation):
    mock_gpt.return_value = odpowiedz_modelu(800, 200)

    process_chat_message(tenant, conversation, "Ile kosztuje strzyżenie?")

    wpis = PromptLog.objects.get()
    assert (wpis.tokens, wpis.tokeny_wejscia, wpis.tokeny_wyjscia) == (1000, 800, 200)


@patch("api.utils.chat_engine.get_openai_response")
def test_wejscie_dominuje_wbrew_dlugosci_tekstow(mock_gpt, tenant, conversation):
    # Sedno poprawki: pytanie krótkie, odpowiedź dłuższa, a mimo to wejście
    # jest cztery razy większe - bo niesie kontekst z bazy wiedzy, którego
    # w logu nie widać. Stary szacunek dawał tu odwrotną proporcję.
    mock_gpt.return_value = {**odpowiedz_modelu(4000, 300), "content": "Długa odpowiedź " * 20}

    process_chat_message(tenant, conversation, "Ile?")

    wpis = PromptLog.objects.get()
    assert wpis.tokeny_wejscia > wpis.tokeny_wyjscia
    assert len(wpis.response) > len(wpis.prompt)


@patch("api.utils.chat_engine.get_openai_response")
def test_awaria_modelu_nie_zapisuje_zmyslonego_rozbicia(mock_gpt, tenant, conversation):
    # Przy nieudanym wywołaniu nie ma czego rozbijać. Zero w kolumnach
    # wyglądałoby jak zmierzone zero i zaniżało średnią kosztu.
    mock_gpt.side_effect = RuntimeError("OpenAI nie odpowiada")

    process_chat_message(tenant, conversation, "Ile kosztuje strzyżenie?")

    wpis = PromptLog.objects.get()
    assert wpis.tokeny_wejscia is None and wpis.tokeny_wyjscia is None


def test_odpowiedz_openai_niesie_obie_liczby():
    # Kontrola pozytywna dla atrapy: gdyby klient OpenAI przestał zwracać
    # rozbicie, testy wyżej dalej by przechodziły na własnych słownikach.
    from api.utils.chat_engine import get_openai_response

    uzycie = SimpleNamespace(total_tokens=1000, prompt_tokens=800, completion_tokens=200)
    odpowiedz = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="tekst"))], usage=uzycie
    )
    with patch("api.utils.chat_engine.get_client") as klient:
        klient.return_value.chat.completions.create.return_value = odpowiedz

        wynik = get_openai_response([{"role": "user", "content": "x"}])

    assert wynik["tokeny_wejscia"] == 800
    assert wynik["tokeny_wyjscia"] == 200


def test_brak_rozbicia_u_dostawcy_zapisuje_pustke_a_nie_smiec():
    # Starsza wersja interfejsu, pośrednik albo inny dostawca mogą podać samą
    # sumę. Zapisanie wtedy czegokolwiek innego niż liczby kończy się śmieciem
    # w kolumnie, który wygląda jak pomiar - albo wywrotką w połowie strumienia,
    # po której ginie odpowiedź już pokazana klientowi na ekranie.
    from api.utils.chat_engine import get_openai_response

    uzycie = SimpleNamespace(total_tokens=1000)  # bez rozbicia
    odpowiedz = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="tekst"))], usage=uzycie
    )
    with patch("api.utils.chat_engine.get_client") as klient:
        klient.return_value.chat.completions.create.return_value = odpowiedz

        wynik = get_openai_response([{"role": "user", "content": "x"}])

    assert wynik["tokens"] == 1000
    assert wynik["tokeny_wejscia"] is None and wynik["tokeny_wyjscia"] is None
