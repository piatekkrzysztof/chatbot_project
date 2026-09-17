"""
Pliki brandingu widgetu znikają razem z firmą i razem z poprzednią wersją.

Logo i awatar zapisują się pod losową nazwą przy każdym wgraniu, więc plik
zastąpiony nowym przestaje być z czymkolwiek powiązany: nie prowadzi do niego
żaden wiersz i nic go nie skasuje. Klient poprawiający logo pięć razy zostawiał
pięć plików, z których cztery były już nie do odnalezienia. Tak samo usunięcie
firmy zabierało wiersz, a obrazy zostawiało w publicznym magazynie.
"""

from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from accounts.models import Tenant
from chatbot_project.pliki import usun_plik_po_zatwierdzeniu

POLA_PLIKOW = ("widget_logo", "widget_avatar")


@receiver(post_delete, sender=Tenant)
def usun_pliki_brandingu(sender, instance, **kwargs):
    for pole in POLA_PLIKOW:
        plik = getattr(instance, pole)
        usun_plik_po_zatwierdzeniu(plik.storage, plik.name)


@receiver(pre_save, sender=Tenant)
def usun_zastapione_pliki_brandingu(sender, instance, raw=False, update_fields=None, **kwargs):
    """
    Kasuje poprzedni obraz, gdy zapis podmienia go na inny.

    `raw=True` znaczy, że zapis pochodzi z `loaddata`, czyli z odtwarzania
    kopii zapasowej. Odtwarzanie wgrywa pliki obok bazy, a nazwy w bazie są
    wtedy nazwami plików, które właśnie przywracamy - skasowanie „poprzedniej"
    wersji usunęłoby dopiero co odtworzony obraz.

    Zapytanie o poprzednie wartości idzie do bazy tylko przy zapisie, który
    tych pól dotyczy. Zwykły `save(update_fields=["name"])` nie kosztuje nic.
    """
    if raw or not instance.pk:
        return
    pola = [p for p in POLA_PLIKOW if update_fields is None or p in update_fields]
    if not pola:
        return
    poprzednie = Tenant.objects.filter(pk=instance.pk).values(*pola).first()
    if not poprzednie:
        return
    for pole in pola:
        stara_nazwa = poprzednie[pole]
        nowy = getattr(instance, pole)
        if stara_nazwa and stara_nazwa != nowy.name:
            usun_plik_po_zatwierdzeniu(nowy.storage, stara_nazwa)
