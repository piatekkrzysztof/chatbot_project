from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"

    def ready(self):
        # Import rejestruje kontrolę ostrzegającą o ulotnym magazynie plików
        import documents.checks  # noqa: F401

        # Import podłącza sygnał, który zleca odczyt pliku i embeddingi po zapisie
        # dokumentu. Bez noqa ruff uznaje go za nieużywany - i tak zniknął
        # w porządkach długu ruff (PR #21, 4.09.2026): od tamtej pory dokument
        # wgrany w panelu nie dostawał embeddingów, a plik dodany w panelu
        # administracyjnym nie był czytany. Testy tego nie widziały, bo same
        # importują ten moduł przy `patch("documents.signals.enqueue")`.
        # Pilnuje tego documents/tests/test_podlaczenie_sygnalow.py.
        import documents.signals  # noqa: F401
