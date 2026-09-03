from django.db.models.signals import post_save
from django.dispatch import receiver

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
    """
    if raw:
        return

    if created and instance.file and not instance.processed:
        enqueue(tasks.extract_text_from_document, instance.id)

    if instance.processed and not instance.chunks.exists():
        enqueue(tasks.generate_embeddings_for_document, instance.id)
