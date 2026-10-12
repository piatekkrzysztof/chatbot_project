"""
Komenda zmierz_czat - rozkład czasu do pierwszego słowa na kroki.

Test obciążenia 12.10.2026: pierwsze słowa p95 3,3 s przy celu 3 s, a z zewnątrz
widać tylko sumę. Komenda idzie na produkcji, więc dwie rzeczy są tu ważniejsze
niż same liczby: nie może niczego zapisać ani naliczyć firmie wiadomości, i musi
wysyłać do modelu to samo co czat (parametry produkcji, strumień).
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import MessageReservation, Tenant
from api.utils.pokrycie import ZNACZNIK_BRAKU
from chat.models import FAQ, ChatMessage, ChatUsageLog, Conversation, PromptLog

KOMENDA = "api.management.commands.zmierz_czat"


def zdarzenie(tresc=None, usage=None):
    z = MagicMock()
    z.choices = [MagicMock(delta=MagicMock(content=tresc))] if tresc is not None else []
    z.usage = usage
    return z


def uzycie(rozumowanie=40, wejscie=900):
    u = MagicMock()
    u.completion_tokens_details.reasoning_tokens = rozumowanie
    u.prompt_tokens = wejscie
    return u


def klient(*kawalki):
    k = MagicMock()
    k.chat.completions.create.side_effect = lambda **_: iter(
        [zdarzenie(t) for t in kawalki] + [zdarzenie(usage=uzycie())]
    )
    return k


def uruchom(capsys, tenant, k, *argumenty):
    with (
        patch(f"{KOMENDA}.get_client", return_value=k),
        patch(f"{KOMENDA}.wektor_pytania", return_value=[0.0] * 3),
        patch(f"{KOMENDA}.szukaj_po_wektorze", return_value=[]),
        patch(f"{KOMENDA}.dolacz_trafienia_slowne", side_effect=lambda *a: a[3]),
    ):
        call_command("zmierz_czat", "--klucz", str(tenant.api_key), *argumenty)
    return capsys.readouterr().out


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")
    FAQ.objects.create(tenant=tenant, question="Godziny otwarcia?", answer="9-17")
    return tenant


def test_rozklada_czas_na_kroki_i_podaje_rozumowanie(capsys, firma):
    wyjscie = uruchom(capsys, firma, klient("Otwarte", " 9-17"), "--pytanie", "Godziny?")

    for opis in ("Wektor pytania", "Wyszukiwanie wektorowe", "FAQ", "Model:", "widgetu"):
        assert opis in wyjscie
    assert "Razem przed wysłaniem do modelu" in wyjscie
    assert "Połączenie z OpenAI: nowy klient" in wyjscie
    assert "rozumowanie 40 tok." in wyjscie and "wejście 900 tok." in wyjscie


def test_niczego_nie_zapisuje_i_nie_nalicza(capsys, firma):
    uruchom(capsys, firma, klient("Tak."))

    assert MessageReservation.objects.count() == 0
    assert ChatMessage.objects.count() == 0
    assert Conversation.objects.count() == 0
    assert PromptLog.objects.count() == 0
    assert ChatUsageLog.objects.count() == 0


def test_wysyla_to_co_czat_strumien_parametry_i_wiedze(capsys, firma, settings):
    settings.OPENAI_REASONING_EFFORT = "medium"
    k = klient("OK")

    uruchom(capsys, firma, k, "--pytanie", "Godziny otwarcia?")

    wywolanie = k.chat.completions.create.call_args.kwargs
    assert wywolanie["stream"] is True
    assert wywolanie["stream_options"] == {"include_usage": True}
    assert wywolanie["reasoning_effort"] == "medium"
    assert wywolanie["model"] == settings.OPENAI_CHAT_MODEL
    system, uzytkownik = wywolanie["messages"]
    assert "9-17" in system["content"]
    assert uzytkownik == {"role": "user", "content": "Godziny otwarcia?"}


def test_domyslnie_pytania_testu_obciazenia(capsys, firma):
    k = klient("OK")

    uruchom(capsys, firma, k)

    assert k.chat.completions.create.call_count == 8


def test_znacznik_braku_opoznia_pierwsze_slowo_widgetu(capsys, firma):
    """Widget pokazuje tekst dopiero po zdjęciu znacznika - pomiar też."""
    zegar = [0.0]

    def klient_z_zegarem(*kawalki):
        def strumien(**_):
            for tresc in kawalki:
                zegar[0] += 0.1  # każdy token przychodzi 100 ms po poprzednim
                yield zdarzenie(tresc)
            yield zdarzenie(usage=uzycie())

        k = MagicMock()
        k.chat.completions.create.side_effect = strumien
        return k

    def pierwsze_slowa(*kawalki):
        with patch(f"{KOMENDA}.time.perf_counter", side_effect=lambda: zegar[0]):
            wyjscie = uruchom(capsys, firma, klient_z_zegarem(*kawalki), "--pytanie", "P?")
        wiersz = next(w for w in wyjscie.splitlines() if w.endswith("P?"))
        return float(wiersz.split("ms")[0]), float(wiersz.split("model")[1].split()[0])

    zwykla = pierwsze_slowa("Nie", " wiem.")
    zegar[0] = 0.0
    ze_znacznikiem = pierwsze_slowa(ZNACZNIK_BRAKU[:5], ZNACZNIK_BRAKU[5:], " Nie wiem.")

    assert zwykla == (100, 100)
    assert ze_znacznikiem == (300, 100)


def test_nieznany_klucz(capsys, db):
    with pytest.raises(CommandError):
        call_command("zmierz_czat", "--klucz", "00000000-0000-0000-0000-000000000000")
    with pytest.raises(CommandError):
        call_command("zmierz_czat", "--klucz", "nie-uuid")
