import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat'

    def ready(self):
        """
        Ostrzeżenie o błędnej konfiguracji poczty przy starcie procesu.

        Tutaj, a nie w settings.py, z dwóch powodów: Django jest już wtedy
        w pełni załadowane (walidator adresu potrzebuje tłumaczeń), a `ready`
        wykonuje się w KAŻDYM procesie — web, workerze i zegarze. To istotne,
        bo obie realne awarie poczty siedziały w różnych usługach, a każda ma
        własny, ręcznie wklepany komplet zmiennych.
        """
        from django.conf import settings

        from chat.kontrola_poczty import problemy_z_konfiguracja

        for problem in problemy_z_konfiguracja(settings):
            # Ostrzeżenie, nie wyjątek: zepsuta poczta nie może przewrócić
            # czatu. Klient woli działającego bota bez powiadomień niż
            # usługę, która nie wstaje.
            logger.warning("Konfiguracja poczty: %s", problem)
