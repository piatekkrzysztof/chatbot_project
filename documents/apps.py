from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'documents'

    def ready(self):
        import documents.signals
        # Import rejestruje kontrolę ostrzegającą o ulotnym magazynie plików
        import documents.checks  # noqa: F401
