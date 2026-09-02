"""
Numer identyfikacji podatkowej: normalizacja i suma kontrolna.

Po co sprawdzać, skoro pole jest opcjonalne: NIP z literówką wygląda jak NIP,
przechodzi przez formularz i wychodzi dopiero na fakturze - czyli po stronie
klienta, przy jego księgowej, kilka tygodni później. Faktura z błędnym NIP-em
wymaga korekty, a klient nie odliczy z niej podatku. Suma kontrolna wyłapuje
przestawione i pomylone cyfry natychmiast, w miejscu, w którym da się je
poprawić bez niczyjego udziału.

To NIE jest sprawdzenie, czy firma istnieje - do tego służy rejestr VAT
Ministerstwa Finansów, czyli zapytanie do zewnętrznej usługi. Tu chodzi
wyłącznie o to, czy ciąg cyfr jest w ogóle poprawnie zbudowany.
"""

#: Wagi z algorytmu sumy kontrolnej NIP. Kolejność ma znaczenie i nie jest
#: dowolna - pochodzi z rozporządzenia, nie z konwencji.
WAGI = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def znormalizuj(numer: str) -> str:
    """
    Same cyfry: bez myślników, spacji i przedrostka kraju.

    Klienci wpisują NIP na kilka sposobów - "PL1234563218", "123-456-32-18",
    "123 456 32 18". Wszystkie znaczą to samo i wszystkie mają się zapisać
    tak samo, inaczej ten sam numer trafiłby do bazy w trzech postaciach.
    """
    czysty = (numer or "").strip().upper()
    if czysty.startswith("PL"):
        czysty = czysty[2:]
    return "".join(znak for znak in czysty if znak.isdigit())


def poprawny(numer: str) -> bool:
    """
    Czy numer ma poprawną budowę i sumę kontrolną.

    Reszta z dzielenia przez 11 równa 10 nie występuje w żadnym prawidłowym
    NIP-ie - taki numer nigdy nie został nadany, więc odrzucamy go zamiast
    przycinać do jednej cyfry.
    """
    cyfry = znormalizuj(numer)
    if len(cyfry) != 10:
        return False

    # Same zera przechodzą sumę kontrolną (0 mod 11 = 0), a żaden numer nigdy
    # nie został tak nadany. Bez tego wiersza pole wypełnione zerami - odruch
    # kogoś, kto chce ominąć wymagany formularz - wyglądałoby na poprawne aż
    # do faktury.
    if set(cyfry) == {"0"}:
        return False

    suma = sum(waga * int(cyfra) for waga, cyfra in zip(WAGI, cyfry[:9]))
    kontrolna = suma % 11

    if kontrolna == 10:
        return False

    return kontrolna == int(cyfry[9])


def sformatuj(numer: str) -> str:
    """NIP w postaci czytelnej dla człowieka: 123-456-32-18."""
    cyfry = znormalizuj(numer)
    if len(cyfry) != 10:
        return numer
    return f"{cyfry[:3]}-{cyfry[3:6]}-{cyfry[6:8]}-{cyfry[8:]}"
