"""
Normalizacja adresów w ustawieniach produkcyjnych.

Dwa wdrożenia zostały już stracone na literówkach w zmiennych: adres backendu
zamiast frontendu w CORS, a potem ukośnik na końcu adresu Vercela, który
django-cors-headers odrzuca jako ścieżkę. Wartości kopiuje się z paska
przeglądarki, więc schemat i ukośnik przychodzą razem z nimi.
"""
import importlib

import pytest


def load_prod_settings(monkeypatch, **env):
    defaults = {
        "DJANGO_SECRET_KEY": "test",
        "DATABASE_URL": "postgres://u:p@localhost:5432/x",
        "DJANGO_ALLOWED_HOSTS": "",
        "DJANGO_CORS_ALLOWED_ORIGINS": "",
        "FRONTEND_URL": "",
        "RENDER_EXTERNAL_HOSTNAME": "",
    }
    defaults.update(env)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)

    # base czyta FRONTEND_URL przy imporcie, a prod dziedziczy przez `import *`,
    # więc bez przeładowania base zostałaby wartość z lokalnego .env
    base = importlib.import_module("chatbot_project.settings.base")
    importlib.reload(base)
    module = importlib.import_module("chatbot_project.settings.prod")
    return importlib.reload(module)


def test_trailing_slash_stripped_from_cors_origin(monkeypatch):
    """django-cors-headers przerywa start, gdy origin ma ścieżkę."""
    prod = load_prod_settings(
        monkeypatch, DJANGO_CORS_ALLOWED_ORIGINS="https://app.vercel.app/"
    )

    assert prod.CORS_ALLOWED_ORIGINS == ["https://app.vercel.app"]


def test_scheme_and_slash_stripped_from_allowed_hosts(monkeypatch):
    """ALLOWED_HOSTS ze schematem nie pasuje do niczego i daje 400."""
    prod = load_prod_settings(
        monkeypatch, DJANGO_ALLOWED_HOSTS="https://api.example.com/, plain.example.com"
    )

    assert prod.ALLOWED_HOSTS == ["api.example.com", "plain.example.com"]


def test_render_hostname_is_added_automatically(monkeypatch):
    prod = load_prod_settings(
        monkeypatch, RENDER_EXTERNAL_HOSTNAME="usluga.onrender.com"
    )

    assert "usluga.onrender.com" in prod.ALLOWED_HOSTS


def test_frontend_url_reaches_cors_and_csrf(monkeypatch):
    """Najczęstsza pomyłka to wpisanie w CORS adresu backendu — stąd ten skrót."""
    prod = load_prod_settings(monkeypatch, FRONTEND_URL="https://app.vercel.app/")

    assert "https://app.vercel.app" in prod.CORS_ALLOWED_ORIGINS
    assert "https://app.vercel.app" in prod.CSRF_TRUSTED_ORIGINS


def test_empty_configuration_yields_empty_lists(monkeypatch):
    prod = load_prod_settings(monkeypatch)

    assert prod.ALLOWED_HOSTS == []
    assert prod.CORS_ALLOWED_ORIGINS == []
