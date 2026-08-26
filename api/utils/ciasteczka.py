"""
Ciasteczko z tokenem odswiezania.

Dlaczego ciasteczko, a nie localStorage: token w localStorage czyta dowolny
skrypt dzialajacy na stronie -- wlasny, z biblioteki albo wstrzykniety. Token
w ciasteczku HttpOnly jest dla JavaScriptu niewidoczny, wiec pojedyncza luka
XSS przestaje oznaczac oddanie sesji.

Dlaczego bez warstwy posredniczacej po stronie Next.js: panel stoi pod
panel.agencjasm-art.pl, API pod api.agencjasm-art.pl. To ta sama domena
rejestrowalna, wiec zapytania miedzy nimi sa "same-site" mimo roznego
subdomeny -- ciasteczko z SameSite=Lax dochodzi normalnie. Gdyby panel stal
pod zupelnie inna domena, Lax by nie wystarczylo i trzeba by albo SameSite=None
(blokowane przez coraz wiecej przegladarek jako ciasteczko trzeciej strony),
albo posrednika. Uklad domen zostal wybrany wczesniej i akurat tu pomaga.

SameSite=Lax zalatwia przy okazji CSRF na koncowce odswiezania: przegladarka
nie dokleja takiego ciasteczka do zapytania POST wychodzacego z cudzej strony,
wiec obca witryna nie odswiezy cudzej sesji.
"""
from django.conf import settings


def ustaw_ciasteczko_odswiezania(odpowiedz, token):
    """Dokleja token odswiezania do odpowiedzi jako ciasteczko HttpOnly."""
    odpowiedz.set_cookie(
        key=settings.NAZWA_CIASTECZKA_ODSWIEZANIA,
        value=str(token),
        httponly=True,
        secure=settings.CIASTECZKO_ODSWIEZANIA_SECURE,
        samesite=settings.CIASTECZKO_ODSWIEZANIA_SAMESITE,
        domain=settings.CIASTECZKO_ODSWIEZANIA_DOMENA,
        path=settings.CIASTECZKO_ODSWIEZANIA_SCIEZKA,
        # Czas zycia ciasteczka rowny czasowi zycia tokenu. Krotsze
        # kazaloby logowac sie mimo wciaz waznego tokenu, dluzsze
        # zostawialoby w przegladarce ciasteczko, ktore juz nic nie otwiera.
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
    )
    _ustaw_znacznik_sesji(odpowiedz)


def _ustaw_znacznik_sesji(odpowiedz):
    """
    Znacznik dla serwera Next.js. Nie niesie tokenu -- tylko informacje, ze
    ta przegladarka ma sesje, zeby dalo sie odmowic trasy przed renderem.
    """
    odpowiedz.set_cookie(
        key=settings.NAZWA_CIASTECZKA_SESJI,
        value="1",
        httponly=True,
        secure=settings.CIASTECZKO_ODSWIEZANIA_SECURE,
        samesite=settings.CIASTECZKO_ODSWIEZANIA_SAMESITE,
        domain=settings.CIASTECZKO_ODSWIEZANIA_DOMENA,
        # Sciezka "/" wlasnie po to, zeby doszlo pod panel, a nie tylko do API.
        path="/",
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
    )


def _usun_znacznik_sesji(odpowiedz):
    odpowiedz.delete_cookie(
        key=settings.NAZWA_CIASTECZKA_SESJI,
        domain=settings.CIASTECZKO_ODSWIEZANIA_DOMENA,
        path="/",
        samesite=settings.CIASTECZKO_ODSWIEZANIA_SAMESITE,
    )


def usun_ciasteczko_odswiezania(odpowiedz):
    """
    Kasuje ciasteczko.

    Domena i sciezka musza byc te same co przy ustawianiu -- inaczej
    przegladarka uzna to za inne ciasteczko i skasuje nieistniejace,
    zostawiajac prawdziwe na miejscu. To cicha awaria: wylogowanie
    wyglada na udane, a sesja zyje dalej.
    """
    odpowiedz.delete_cookie(
        key=settings.NAZWA_CIASTECZKA_ODSWIEZANIA,
        domain=settings.CIASTECZKO_ODSWIEZANIA_DOMENA,
        path=settings.CIASTECZKO_ODSWIEZANIA_SCIEZKA,
        samesite=settings.CIASTECZKO_ODSWIEZANIA_SAMESITE,
    )
    _usun_znacznik_sesji(odpowiedz)


def odczytaj_token_odswiezania(zadanie):
    """Token z ciasteczka, a gdy go nie ma -- z tresci zadania."""
    z_ciasteczka = zadanie.COOKIES.get(settings.NAZWA_CIASTECZKA_ODSWIEZANIA)
    if z_ciasteczka:
        return z_ciasteczka
    # Zgodnosc wsteczna na czas wdrozenia frontendu oraz dla klientow
    # spoza przegladarki, ktore ciasteczek nie prowadza.
    return (zadanie.data or {}).get("refresh")
