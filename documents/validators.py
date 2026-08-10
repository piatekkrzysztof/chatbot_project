"""
Limit wielkości bazy wiedzy.

Poprzednia wersja miała dwie wady i obie były ciche. Po pierwsze, trzymała
własny słownik planów ("free", "pro", "enterprise") niepodpięty do katalogu —
po zmianie cennika "start" i "grow" nie pasowały do niczego i wpadały
w wartość domyślną przewidzianą dla planu darmowego, więc klient płacący
349 zł miał limit klienta darmowego. Po drugie, i poważniej, walidator siedział
w `DocumentSerializer.validate()`, a oba widoki korzystające z tego serializera
są tylko do odczytu — upload tworzy dokument bezpośrednio. Metoda nigdy się
nie wykonywała i limit nie działał nigdy, nie tylko po zmianie cennika.

Mierzymy wyodrębniony tekst, nie rozmiar pliku. Strony WWW nie mają pliku,
a stanowią drugą drogę dodawania wiedzy — liczenie bajtów pliku pomijałoby
je w całości i limit dałoby się obejść, dodając stronę zamiast dokumentu.
Tekst jest też tym, co realnie kosztuje: embeddingi liczymy od znaków.
"""
from django.db.models import Sum
from django.db.models.functions import Length
from rest_framework.exceptions import ValidationError

from accounts.plans import get_plan
from documents.models import Document

# Plan spoza katalogu (subskrypcja sprzed cennika, brak subskrypcji, literówka).
# Odpowiada najniższemu planowi: na tyle dużo, żeby nie zablokować klienta,
# którego wpis dopiero poprawimy, i na tyle mało, żeby nie rozdawać za darmo
# limitu z najwyższego planu.
DOMYSLNY_LIMIT_MB = 5

MB = 1024 * 1024


def limit_bazy_wiedzy_mb(tenant):
    """Ile megabajtów wiedzy przysługuje firmie wedle jej planu."""
    subskrypcja = getattr(tenant, "subscription", None)
    plan = get_plan(getattr(subskrypcja, "plan_type", None))
    return plan.knowledge_base_mb if plan else DOMYSLNY_LIMIT_MB


def rozmiar_bazy_wiedzy(tenant):
    """
    Rozmiar wyodrębnionego tekstu wszystkich dokumentów firmy, w bajtach.

    Liczymy w bazie, a nie w Pythonie: przy większej bazie wiedzy wciągnięcie
    treści wszystkich dokumentów do pamięci tylko po to, żeby je zmierzyć,
    byłoby kosztowniejsze niż sam upload.
    """
    wynik = (
        Document.objects
        .filter(tenant=tenant)
        .aggregate(razem=Sum(Length("content")))
    )
    return wynik["razem"] or 0


def sprawdz_limit_bazy_wiedzy(tenant, dodawany_tekst=""):
    """
    Rzuca ValidationError, gdy nowa treść nie zmieści się w limicie planu.

    Sprawdzamy przed zapisem, nie po: dokument zapisany i zaraz usunięty
    zostawiałby po sobie plik w magazynie i zadanie embeddingów w kolejce.
    """
    limit_mb = limit_bazy_wiedzy_mb(tenant)
    limit_bajtow = limit_mb * MB

    obecnie = rozmiar_bazy_wiedzy(tenant)
    po_dodaniu = obecnie + len(dodawany_tekst or "")

    if po_dodaniu > limit_bajtow:
        raise ValidationError(
            f"Baza wiedzy przekroczyłaby limit {limit_mb} MB dla Twojego planu "
            f"(obecnie {obecnie / MB:.1f} MB). Usuń część materiałów "
            f"albo przejdź na wyższy plan."
        )
