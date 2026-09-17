from functools import partial

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from chatbot_project.pliki import usun_plik_po_zatwierdzeniu
from documents import tasks
from documents.models import Document
from documents.utils.queue import enqueue


@receiver(post_save, sender=Document)
def handle_new_document(sender, instance, created, raw=False, **kwargs):
    """
    Uruchamia przetwarzanie dokumentu po jego zapisaniu.

    `raw=True` znaczy, że zapis pochodzi z `loaddata` - czyli z odtwarzania
    kopii zapasowej. Wtedy wychodzimy natychmiast, i to nie jest ostrożność
    na zapas:

    Fragmenty wczytują się z pliku PO dokumentach, więc w chwili zapisu
    dokumentu `chunks.exists()` jest fałszywe dla każdego z nich. Bez tego
    warunku odtwarzanie zlecało generowanie embeddingów dla CAŁEJ bazy -
    czyli płatne wywołania OpenAI dla danych, których gotowe wektory leżą
    dwa ekrany dalej w tym samym pliku. Przy nieczynnym Celery `enqueue`
    wykonuje zadanie na miejscu, więc samo odtwarzanie robiło te wywołania
    w locie i mogło paść w połowie.

    Znalezione przy pierwszej próbie odtworzenia z kopii, nie przy przeglądzie
    kodu: w logu wczytywania pojawiły się wpisy o zlecaniu zadań dla
    dokumentów, które nie miały prawa niczego uruchamiać.

    Zlecenia czekają na zatwierdzenie transakcji (F10). Zapis dokumentu pod
    blokadą limitu wiedzy dzieje się w `transaction.atomic()`, a worker
    uruchomiony przed zatwierdzeniem nie widzi jeszcze dokumentu - zadanie
    embeddingów kończy się wtedy po cichu i dokument zostaje bez fragmentów.
    Wycofana transakcja nie zleca niczego. Poza transakcją Django wykonuje
    `on_commit` od razu, więc zwykły zapis działa jak dotąd.
    """
    if raw:
        return

    if created and instance.file and not instance.processed:
        transaction.on_commit(partial(enqueue, tasks.extract_text_from_document, instance.id))

    if instance.processed and not instance.chunks.exists():
        transaction.on_commit(partial(enqueue, tasks.generate_embeddings_for_document, instance.id))


@receiver(post_delete, sender=Document)
def usun_plik_dokumentu(sender, instance, **kwargs):
    """
    Usuwa plik z prywatnego magazynu razem z dokumentem - każdą drogą.

    Kasowanie pliku było wcześniej dopisane w widoku panelu (2.8.0), czyli
    w jednej z dróg, którymi dokument znika. Panel administracyjny, usunięcie
    firmy, `queryset.delete()` z powłoki i żądanie klienta o skasowanie danych
    zabierały wiersz, a plik zostawiały w magazynie - bez wiersza nikt go już
    nie znajdzie i nikt nie skasuje.

    Sygnał, a nie nadpisany `Document.delete()`: `queryset.delete()` nie woła
    metody modelu dla żadnego wiersza, a kaskada przy usuwaniu firmy nie woła
    jej tym bardziej. `post_delete` dostaje każdy usunięty wiersz.
    """
    usun_plik_po_zatwierdzeniu(instance.file.storage, instance.file.name)
