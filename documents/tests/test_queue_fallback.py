"""
Wgranie dokumentu nie może zależeć od działającego brokera.

Produkcja pokazała dwie przyczyny naraz: w zależnościach brakowało sterownika
`redis`, więc `.delay()` wywalało się od razu, a darmowy plan Render nie
udostępnia procesów w tle, więc zadania i tak nie miałyby kto wykonać.
Obie kończyły się błędem 500 przy dodawaniu dokumentu.
"""
from unittest.mock import MagicMock

import pytest

from documents.utils.queue import enqueue


def test_uses_queue_when_broker_available():
    task = MagicMock()

    assert enqueue(task, 42) is True
    task.delay.assert_called_once_with(42)
    task.assert_not_called()


def test_runs_inline_when_dispatch_fails():
    task = MagicMock()
    task.delay.side_effect = AttributeError("brak sterownika redis")
    task.name = "zadanie.testowe"

    assert enqueue(task, 42) is False
    task.assert_called_once_with(42)


def test_inline_failure_is_not_swallowed():
    """Błąd samego zadania musi być widoczny, nie zamieciony pod dywan."""
    task = MagicMock()
    task.delay.side_effect = OSError("broker nieosiągalny")
    task.side_effect = ValueError("zadanie faktycznie padło")
    task.name = "zadanie.testowe"

    with pytest.raises(ValueError):
        enqueue(task, 42)


@pytest.mark.django_db
def test_document_upload_survives_broken_broker(monkeypatch, tenant, valid_pdf_file):
    """Dokument musi zostać zapisany i przetworzony, nawet gdy kolejka nie działa."""
    from documents import tasks
    from documents.models import Document

    def zawsze_pada(*args, **kwargs):
        raise AttributeError("broker niedostępny")

    monkeypatch.setattr(tasks.extract_text_from_document, "delay", zawsze_pada)
    monkeypatch.setattr(tasks.generate_embeddings_for_document, "delay", zawsze_pada)
    monkeypatch.setattr(
        "documents.utils.embedding_generator.generate_embeddings_for_document",
        lambda doc: None,
    )

    document = Document.objects.create(tenant=tenant, name="awaria.pdf", file=valid_pdf_file)
    document.refresh_from_db()

    assert document.processed is True
    assert "Test PDF content" in document.content
