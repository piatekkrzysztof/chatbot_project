from celery import shared_task

from chat.retention import purge_all_tenants


@shared_task
def purge_expired_conversations():
    """Codzienne czyszczenie danych rozmów po okresie retencji każdego klienta."""
    return purge_all_tenants()
