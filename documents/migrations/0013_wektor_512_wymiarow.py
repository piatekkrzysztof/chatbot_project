"""
Skrócenie wektora z 1536 do 512 wymiarów.

Kategoria ryzyka: MIGRACJA NISZCZĄCA. Ta migracja KASUJE WSZYSTKIE FRAGMENTY.

Dlaczego nie da się inaczej
---------------------------
Postgres nie przepisze wektora o 1536 liczbach do kolumny `vector(512)` -
i słusznie, bo nie ma czym wypełnić brakującej informacji. Obcięcie pierwszych
512 liczb nie jest tym samym, co wektor policzony z parametrem `dimensions`:
model normalizuje wynik pod zadaną długość. Cichy `USING embedding[1:512]`
dałby wektory, które wyglądają poprawnie i mierzą inne odległości.

Fragmenty są danymi pochodnymi. Cała ich treść siedzi w `Document.content`,
więc kasowanie niczego nie traci bezpowrotnie - trzeba je tylko przeliczyć.

Co się dzieje między migracją a przeliczeniem
---------------------------------------------
Baza wiedzy jest pusta, więc `query_similar_chunks_pgvector` nie zwraca nic
i bot mówi, że nie wie. To jest właściwa awaria: bot milczy, zamiast odpowiadać
z połowy bazy albo cytować fragmenty policzone innym wymiarem.

Okno trwa tyle, ile przeliczenie. Przy stanie z 7 września 2026 - około 300
fragmentów u wszystkich klientów razem - są to sekundy.

Kolejność wdrożenia jest w docs/zmiana-wymiaru-wektora.md i sprowadza się do:

    python manage.py migrate
    python manage.py przelicz_fragmenty --wykonaj

Wycofanie
---------
`migrate documents 0012` wraca do 1536 wymiarów i również kasuje fragmenty,
z tego samego powodu w drugą stronę. Po wycofaniu trzeba przeliczyć jeszcze
raz - i cofnąć RAG_MAX_DISTANCE na serwerze do 1.0.
"""

from django.db import migrations
from pgvector.django import VectorField

#: Wpisane wprost, nie zaimportowane z documents.wymiar.
#:
#: Migracja jest zapisem tego, co juz sie stalo. Gdyby brala wymiar ze stalej,
#: zmiana tej stalej na 256 zmienilaby wstecz znaczenie tej migracji, a bazy,
#: ktore ja juz wykonaly, zostalyby na 512 - i nikt by tego nie zauwazyl.
#: Zgodnosc miedzy stala a schematem pilnuje documents/tests/test_wymiar.py.
WYMIAR = 512


def wyczysc_fragmenty(apps, schema_editor):
    """
    Kasuje fragmenty, bo ich wektory mają starą długość.

    Osobnym krokiem, przed zmianą typu kolumny: `ALTER COLUMN ... TYPE`
    na niepustej tabeli wywaliłby się na pierwszym wierszu z komunikatem
    o niezgodnej liczbie wymiarów, w połowie wdrożenia.
    """
    DocumentChunk = apps.get_model("documents", "DocumentChunk")
    ile = DocumentChunk.objects.count()
    DocumentChunk.objects.all().delete()

    if ile:
        # Wypisane, nie zalogowane: to jedyny moment, w ktorym widac skale
        # tego, co trzeba przeliczyc, a osoba wdrazajaca patrzy wlasnie
        # w te konsole.
        print(f"\n  Skasowano {ile:,} fragmentow o starym wymiarze wektora.")
        print("  Bot nie odpowie z bazy wiedzy, dopoki nie przeliczysz:")
        print("    python manage.py przelicz_fragmenty --wykonaj\n")


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0012_znakow_na_stronie"),
    ]

    operations = [
        migrations.RunPython(wyczysc_fragmenty, wyczysc_fragmenty),
        migrations.AlterField(
            model_name="documentchunk",
            name="embedding",
            field=VectorField(dimensions=WYMIAR),
        ),
    ]
