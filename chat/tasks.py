from celery import shared_task

from chat.retention import purge_all_tenants


@shared_task
def purge_expired_conversations():
    """Codzienne czyszczenie danych rozmów po okresie retencji każdego klienta."""
    return purge_all_tenants()


@shared_task
def powiadom_o_zapytaniu_task(contact_request_id):
    """
    Powiadomienie o nowym zapytaniu, poza żądaniem HTTP.

    Wysyłka szła dotąd wewnątrz widoku, więc odwiedzający czekał na
    potwierdzenie tyle, ile trwało połączenie z serwerem poczty. To jest
    najgorszy moment na czekanie: ktoś właśnie zostawił swój numer i widzi
    kręcące się kółko.
    """
    from chat.powiadomienia import powiadom_o_zapytaniu

    powiadom_o_zapytaniu(contact_request_id)
