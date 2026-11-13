"""
Działania panelu, które kosztują, tylko przy ważnym planie (przegląd 2026-11, R10).

Czat testowy (odpowiedzi modelu), wgranie dokumentu (embeddingi) oraz dodanie
i ręczne odświeżenie strony WWW (pobieranie i embeddingi) płacimy my. Do
2.32.26 nie sprawdzały planu: po końcu okresu próbnego albo bez subskrypcji
firma miała 100 odpowiedzi modelu dziennie w czacie testowym i nieograniczone
odświeżanie stron - bez końca i bez płacenia.

„Ważny plan" to ta sama reguła co dla widgetu (`Subscription.daje_dostep`):
skoro bot nie odpowiada odwiedzającym, nie ma też czego testować ani karmić.
Podgląd panelu, FAQ, ustawienia, usuwanie danych i eksport działają dalej -
klient po zakupie wraca do przygotowanej bazy, a bez zakupu może zabrać swoje
dane.

402, nie 403: panel czyta 403 jako brak uprawnień roli i potrafi wtedy chować
całe sekcje. Tu rola jest w porządku - brakuje planu.
"""

from django.utils import timezone
from rest_framework.exceptions import APIException

from accounts.models import Subscription


class BrakWaznegoPlanu(APIException):
    status_code = 402
    default_detail = "To wymaga aktywnego planu. Wybierz plan w zakładce Subskrypcja."
    default_code = "brak_planu"


def wymagaj_waznego_planu(tenant, czynnosc):
    """
    Rzuca BrakWaznegoPlanu (402), gdy firma nie ma dziś ważnej subskrypcji.

    Subskrypcja czytana z bazy, nie z `tenant.subscription`: obiekt firmy
    w żądaniu mógł zapamiętać stan sprzed wygaśnięcia albo zakupu.
    """
    subskrypcja = Subscription.objects.filter(tenant=tenant).first()
    if subskrypcja is not None and subskrypcja.daje_dostep(timezone.now().date()):
        return
    raise BrakWaznegoPlanu(
        f"{czynnosc} wymaga aktywnego planu - chatbot bez niego nie odpowiada "
        f"odwiedzającym. Wybierz plan w zakładce Subskrypcja."
    )
