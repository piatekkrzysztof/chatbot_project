"""
Kasowanie plików z magazynu razem z wierszem, do którego należały.

Magazyn plików nie jest częścią bazy danych i nie bierze udziału w jej
transakcjach. Z tego wynikają obie zasady poniżej:

* kasujemy **po** zatwierdzeniu transakcji, bo wycofana transakcja przywraca
  wiersz, a skasowanego pliku nie przywróci nikt - kopii nie trzymamy;
* błąd magazynu **nie przerywa** operacji, bo wiersza i tak nie da się już
  cofnąć. Plik bez wiersza to śmieć do posprzątania, nie awaria dla klienta.
  Zostaje po nim nazwa w logu, żeby dało się go odnaleźć.
"""

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def usun_plik_po_zatwierdzeniu(magazyn, nazwa):
    """Zleca usunięcie pliku po zatwierdzeniu bieżącej transakcji."""
    if not nazwa:
        return
    transaction.on_commit(lambda: usun_plik_teraz(magazyn, nazwa))


def usun_plik_teraz(magazyn, nazwa):
    try:
        magazyn.delete(nazwa)
    except Exception:
        logger.exception("Nie udało się usunąć pliku %s z magazynu", nazwa)
