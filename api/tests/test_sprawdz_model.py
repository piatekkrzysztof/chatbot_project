"""
Komenda sprawdz_model - ostatnia bramka przed podmianą modelu.

Kategoria ryzyka: AWARIA CAŁEGO CZATU, BEZ ALERTU. Model, który odrzuca któryś
z wysyłanych parametrów, oddaje błąd 400 przy każdym pytaniu, a bot odpowiada
wszystkim klientom komunikatem awaryjnym. 8.10.2026, przed przejściem na
gpt-6-luna: model odrzuca temperaturę 0,2 (ustawioną na produkcji), gpt-4o-mini
odrzuca reasoning_effort, a gpt-5-nano przy limicie 600 tokenów zwraca pustą
odpowiedź - całe tokeny idą na rozumowanie.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from api.utils.chat_engine import parametry_modelu


def zwykla(tresc="OK", rozumowanie=12):
    odp = MagicMock()
    odp.choices = [MagicMock(message=MagicMock(content=tresc))]
    odp.usage.total_tokens = 40
    odp.usage.completion_tokens_details.reasoning_tokens = rozumowanie
    return odp


def strumien(tresc="OK"):
    zdarzenie = MagicMock()
    zdarzenie.choices = [MagicMock(delta=MagicMock(content=tresc))]
    return iter([zdarzenie] if tresc else [])


def uruchom(klient, capsys):
    with patch("api.management.commands.sprawdz_model.get_client", return_value=klient):
        try:
            call_command("sprawdz_model")
            kod = 0
        except SystemExit as wyjscie:
            kod = wyjscie.code
    return kod, capsys.readouterr().out


def klient_z(zwykla_odp, strumien_odp):
    klient = MagicMock()
    klient.chat.completions.create.side_effect = [zwykla_odp, strumien_odp]
    return klient


def test_dziala_i_sprawdza_takze_strumien(capsys):
    klient = klient_z(zwykla(), strumien())

    kod, wyjscie = uruchom(klient, capsys)

    assert kod == 0
    assert "DZIALA" in wyjscie and "pierwsze slowa" in wyjscie
    wywolania = klient.chat.completions.create.call_args_list
    assert len(wywolania) == 2
    assert wywolania[1].kwargs["stream"] is True
    assert wywolania[1].kwargs["stream_options"] == {"include_usage": True}


@override_settings(OPENAI_REASONING_EFFORT="medium", OPENAI_TEMPERATURE=None)
def test_obie_proby_ida_z_parametrami_produkcji(capsys):
    """Ten test padał przed 2.27.0: reasoning_effort nie istniał w parametrach."""
    klient = klient_z(zwykla(), strumien())

    uruchom(klient, capsys)

    for wywolanie in klient.chat.completions.create.call_args_list:
        assert wywolanie.kwargs["reasoning_effort"] == "medium"
        assert "temperature" not in wywolanie.kwargs


def test_pusta_odpowiedz_to_porazka(capsys):
    """Ten test padał przed 2.27.0: pusta odpowiedź przechodziła jako „DZIALA"."""
    kod, wyjscie = uruchom(klient_z(zwykla(tresc=""), strumien("")), capsys)

    assert kod == 1
    assert "pusta" in wyjscie
    assert "OPENAI_REASONING_EFFORT" in wyjscie


def test_pusty_strumien_to_porazka(capsys):
    kod, _ = uruchom(klient_z(zwykla(), strumien("")), capsys)

    assert kod == 1


def test_odrzucony_reasoning_effort_dostaje_podpowiedz(capsys):
    klient = MagicMock()
    klient.chat.completions.create.side_effect = Exception(
        "Error code: 400 - Unsupported parameter: 'reasoning_effort' is not supported."
    )

    kod, wyjscie = uruchom(klient, capsys)

    assert kod == 1
    assert "NIE DZIALA" in wyjscie
    assert "wyczysc te zmienna" in wyjscie


def test_odrzucona_temperatura_dostaje_podpowiedz(capsys):
    klient = MagicMock()
    klient.chat.completions.create.side_effect = Exception(
        "Unsupported value: 'temperature' does not support 0.2 with this model."
    )

    kod, wyjscie = uruchom(klient, capsys)

    assert kod == 1
    assert "OPENAI_TEMPERATURE" in wyjscie


def test_blad_tylko_w_strumieniu_tez_jest_porazka(capsys):
    """Widget idzie strumieniem - zwykłe wywołanie, które przechodzi, nie wystarcza."""
    klient = klient_z(zwykla(), Exception("stream_options is not supported"))

    kod, wyjscie = uruchom(klient, capsys)

    assert kod == 1
    assert "NIE DZIALA" in wyjscie


@pytest.mark.parametrize("wartosc,oczekiwane", [(None, False), ("low", True), ("medium", True)])
def test_reasoning_effort_tylko_gdy_ustawiony(wartosc, oczekiwane):
    """gpt-4o-mini odrzuca reasoning_effort - pusta zmienna znaczy „nie wysyłaj"."""
    with override_settings(OPENAI_REASONING_EFFORT=wartosc):
        parametry = parametry_modelu()

    assert ("reasoning_effort" in parametry) is oczekiwane
    if oczekiwane:
        assert parametry["reasoning_effort"] == wartosc
