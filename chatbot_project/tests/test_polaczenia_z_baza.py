"""
Połączenia z bazą utrzymywane między żądaniami (2.32.1).

Test obciążenia 12.10.2026: p50 ~750 ms nawet dla ustawień widgetu. Pomiar
w powłoce produkcji: CONN_MAX_AGE=0, nowe połączenie z bazą 330-740 ms,
zapytanie na otwartym 2 ms - każde żądanie płaciło za samo łączenie.
"""

from chatbot_project.tests.test_prod_settings import load_prod_settings


def test_produkcja_utrzymuje_polaczenia_i_sprawdza_je_przed_uzyciem(monkeypatch):
    prod = load_prod_settings(monkeypatch)
    baza = prod.DATABASES["default"]

    assert baza["CONN_MAX_AGE"] == 60
    assert baza["CONN_HEALTH_CHECKS"] is True


def test_czas_utrzymania_mozna_zmienic_zmienna(monkeypatch):
    """Awaryjnie, bez wdrażania kodu: DB_CONN_MAX_AGE=0 wraca do starego zachowania."""
    prod = load_prod_settings(monkeypatch, DB_CONN_MAX_AGE="0")

    assert prod.DATABASES["default"]["CONN_MAX_AGE"] == 0
