"""
Jeden punkt zlecania zadań w tle.

Zlecenie do Celery zawodzi w dwóch realnych sytuacjach: gdy broker jest
nieosiągalny i gdy w środowisku nie ma workerów (darmowy plan Render nie
udostępnia procesów w tle). W obu przypadkach `.delay()` rzucało wyjątek,
przez co wgranie dokumentu kończyło się błędem 500, a dokument przepadał.

Tutaj próbujemy zlecić zadanie, a jeśli to niemożliwe — wykonujemy je od razu.
Wolniej, ale użytkownik dostaje działającą funkcję zamiast błędu.
"""
import logging

logger = logging.getLogger(__name__)


def enqueue(task, *args, **kwargs):
    """
    Zleca zadanie do kolejki; przy braku brokera wykonuje je synchronicznie.
    Zwraca True, jeśli poszło do kolejki, False jeśli wykonano na miejscu.
    """
    try:
        task.delay(*args, **kwargs)
        return True
    except Exception as e:
        logger.warning(
            "Nie udało się zlecić zadania %s (%s) — wykonuję synchronicznie.",
            getattr(task, "name", task), type(e).__name__,
        )
        task(*args, **kwargs)
        return False
