import pytest


@pytest.fixture(autouse=True)
def synthetic_backup_key(settings):
    # Wyłącznie dane testowe; produkcja nie ma domyślnego klucza.
    settings.BACKUP_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
