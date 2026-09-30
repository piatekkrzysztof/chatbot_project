from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        import stripe

        # Checkout trzyma krótką blokadę własnego slotu podczas komunikacji.
        # Awaria Stripe nie może zajmować procesu przez domyślne 80 sekund.
        stripe.default_http_client = stripe.http_client.RequestsClient(timeout=10)

        # Import rejestruje kontrolę ostrzegającą o limitach liczonych per proces
        import api.checks  # noqa: F401
        import api.schema_auth  # noqa: F401

        # Widget siedzi na witrynach klientów, których adresów nie znamy z góry —
        # bez tego przeglądarka odwiedzającego blokuje jego zapytania
        from api.cors import podepnij

        podepnij()
