"""
Kompletność schematu OpenAPI.

drf-spectacular nie przerywa generowania, gdy nie potrafi opisać widoku — po
cichu go pomija. Przy pierwszym podejściu wypadło w ten sposób 20 endpointów,
w tym cały publiczny widget, czyli dokładnie to, od czego zaczyna ktoś
integrujący czat ze swoją stroną. Dokumentacja, która milczy o połowie API,
myli bardziej niż jej brak.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

# Ścieżki, bez których nie da się osadzić widgetu ani obsłużyć klienta
WYMAGANE_SCIEZKI = [
    "/api/widget-settings/",
    "/api/widget/chat/",
    "/api/widget/chat/stream/",
    "/api/widget/faq/",
    "/api/widget/contact/",
    "/api/accounts/login/",
    "/api/accounts/me/",
    "/api/accounts/accept-invite/",
    "/api/knowledge/",
    "/api/privacy/",
    "/api/analytics/",
]


@pytest.fixture
def schema():
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def test_schemat_zawiera_kluczowe_endpointy(schema):
    brakujace = [p for p in WYMAGANE_SCIEZKI if p not in schema["paths"]]

    assert brakujace == [], f"Schemat pomija: {brakujace}"


def test_schemat_generuje_sie_bez_bledow(capsys):
    """Błędy generatora lecą na stderr, a polecenie i tak kończy się sukcesem."""
    from drf_spectacular.generators import SchemaGenerator

    SchemaGenerator().get_schema(request=None, public=True)
    komunikaty = capsys.readouterr()

    assert "Error [" not in komunikaty.err, komunikaty.err


def test_kazda_operacja_ma_sekcje(schema):
    """Bez tagu endpoint ląduje w zbiorczej sekcji 'api' i nikt go tam nie znajdzie."""
    bez_tagu = []
    for sciezka, operacje in schema["paths"].items():
        for metoda, operacja in operacje.items():
            if metoda not in ("get", "post", "put", "patch", "delete"):
                continue
            tagi = operacja.get("tags", [])
            if not tagi or tagi == ["api"]:
                bez_tagu.append(f"{metoda.upper()} {sciezka}")

    assert bez_tagu == [], f"Operacje bez sekcji: {bez_tagu}"


@pytest.mark.django_db
def test_swagger_jest_dostepny():
    response = APIClient().get("/docs/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_schemat_jest_dostepny_pod_wlasnym_adresem():
    """
    Celowo poza /api/ — TenantMiddleware wymaga tam tenanta, więc schemat
    byłby nie do odczytania dla kogoś, kto dopiero szuka, jak się połączyć.
    """
    response = APIClient().get("/schema/")

    assert response.status_code == 200
