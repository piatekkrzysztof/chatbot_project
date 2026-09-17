from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Import podłącza sygnały kasujące pliki brandingu razem z firmą
        # i razem z poprzednią wersją obrazu. Bez noqa ruff uznaje go za
        # nieużywany i usuwa - tak zniknął kiedyś sygnał dokumentów (PR #21),
        # a dokumenty przez tydzień nie dostawały embeddingów.
        import accounts.signals  # noqa: F401
