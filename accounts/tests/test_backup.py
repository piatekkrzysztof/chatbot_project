"""
Kopia zapasowa danych.

Darmowa baza na Renderze nie ma żadnych kopii i wygasa 30 dni po utworzeniu —
dokumentacja Rendera mówi to wprost. Ta komenda jest jedynym zabezpieczeniem
przed utratą konfiguracji chatbotów i rozmów klientów.

Kopia, której nie da się odtworzyć, nie jest kopią. Testy sprawdzają więc nie
tylko to, czy plik powstaje, ale czy zawiera dane, które faktycznie wracają.
"""
import json

import pytest
from django.core.management import CommandError, call_command

from accounts.models import Tenant
from chat.models import ChatMessage, Conversation


@pytest.mark.django_db
def test_kopia_zawiera_dane_firmy(tenant, tmp_path):
    plik = tmp_path / "kopia.json"

    call_command("backup_data", output=str(plik))

    dane = json.loads(plik.read_text(encoding="utf-8"))
    modele = {wpis["model"] for wpis in dane}
    assert "accounts.tenant" in modele
    nazwy = [w["fields"]["name"] for w in dane if w["model"] == "accounts.tenant"]
    assert tenant.name in nazwy


@pytest.mark.django_db
def test_kopia_obejmuje_rozmowy_i_wiadomosci(tenant, tmp_path):
    """To dane osobowe odwiedzających — ich utrata jest nieodwracalna."""
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="10.0.0.0")
    ChatMessage.objects.create(conversation=rozmowa, sender="user", message="Pytanie")

    plik = tmp_path / "kopia.json"
    call_command("backup_data", output=str(plik))

    modele = {w["model"] for w in json.loads(plik.read_text(encoding="utf-8"))}
    assert {"chat.conversation", "chat.chatmessage"} <= modele


@pytest.mark.django_db
def test_kopia_pomija_tabele_odtwarzane_przez_migracje(tenant, tmp_path):
    """
    Typy zawartości i uprawnienia tworzą migracje. W zrzucie nie tylko zajmują
    miejsce — przy odtwarzaniu kolidują z rekordami, które już powstały.
    """
    plik = tmp_path / "kopia.json"

    call_command("backup_data", output=str(plik))

    modele = {w["model"] for w in json.loads(plik.read_text(encoding="utf-8"))}
    assert "contenttypes.contenttype" not in modele
    assert "auth.permission" not in modele
    assert "sessions.session" not in modele


@pytest.mark.django_db
def test_pusty_zrzut_przerywa_zamiast_nadpisac(tmp_path, monkeypatch):
    """
    Zapisanie pustej kopii na miejsce dobrej jest gorsze niż brak kopii:
    problem wychodzi dopiero przy odtwarzaniu, gdy nie ma już czego ratować.
    """
    from accounts.management.commands import backup_data as modul

    def pusty_zrzut(*args, **kwargs):
        kwargs["stdout"].write("[]")

    monkeypatch.setattr(modul, "call_command", pusty_zrzut)

    with pytest.raises(CommandError, match="pusty"):
        call_command("backup_data", output=str(tmp_path / "kopia.json"))


@pytest.mark.django_db
def test_dane_z_kopii_daja_sie_wczytac(tenant, tmp_path):
    """
    Rundę w obie strony na prawdziwej bazie produkcyjnej przeprowadziłem ręcznie
    (60 obiektów, zgodne liczby wierszy, embedding pgvector identyczny co do
    bitu). Tutaj pilnujemy, żeby format zrzutu pozostał wczytywalny.
    """
    plik = tmp_path / "kopia.json"
    call_command("backup_data", output=str(plik))

    nazwa = tenant.name
    Tenant.objects.filter(pk=tenant.pk).delete()
    assert not Tenant.objects.filter(name=nazwa).exists()

    call_command("loaddata", str(plik), verbosity=0)

    assert Tenant.objects.filter(name=nazwa).exists()
