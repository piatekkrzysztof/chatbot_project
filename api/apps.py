from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        # Import rejestruje kontrolę ostrzegającą o limitach liczonych per proces
        import api.checks  # noqa: F401
