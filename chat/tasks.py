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


@shared_task
def powiadom_o_rozmowie_task(conversation_id):
    """Powiadomienie o rozpoczętej rozmowie, poza żądaniem HTTP."""
    from chat.powiadomienia import powiadom_o_rozmowie

    powiadom_o_rozmowie(conversation_id)


@shared_task
def sprawdz_poczte_task(adres_testowy=None):
    """
    To samo sprawdzenie, ale wykonane w procesie workera.

    Powłoka Rendera podpina się wyłącznie do usługi web, więc konfiguracji
    workera nie da się obejrzeć bezpośrednio — a to on realnie wysyła
    powiadomienia i to na nim siedziała literówka w adresie nadawcy.
    Zlecenie tego zadania i odczytanie wyniku to jedyny sposób, żeby
    zobaczyć jego ustawienia.
    """
    from chat.management.commands.sprawdz_poczte import zbadaj_poczte

    return zbadaj_poczte(adres_testowy)
