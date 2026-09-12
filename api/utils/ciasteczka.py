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

SameSite nie chroni przed inną subdomeną tej samej witryny. Źródło żądania
sprawdza SessionBoundaryMixin. Token jest host-only; wspólna domena dotyczy
wyłącznie znacznika panelu. Produkcja używa prefiksu __Host- i ścieżki /.
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
        domain=None,
        path=settings.CIASTECZKO_ODSWIEZANIA_SCIEZKA,
        # Czas zycia ciasteczka rowny czasowi zycia tokenu. Krotsze
        # kazaloby logowac sie mimo wciaz waznego tokenu, dluzsze
        # zostawialoby w przegladarce ciasteczko, ktore juz nic nie otwiera.
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
    )
    _usun_stare_ciasteczko(odpowiedz)
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
        domain=None,
        path=settings.CIASTECZKO_ODSWIEZANIA_SCIEZKA,
        samesite=settings.CIASTECZKO_ODSWIEZANIA_SAMESITE,
    )
    _usun_stare_ciasteczko(odpowiedz)
    _usun_znacznik_sesji(odpowiedz)


def odczytaj_token_odswiezania(zadanie):
    """Wyłącznie nowe ciasteczko; stary token z localStorage nie odtwarza sesji."""
    return zadanie.COOKIES.get(settings.NAZWA_CIASTECZKA_ODSWIEZANIA)


def _usun_stare_ciasteczko(odpowiedz):
    odpowiedz.delete_cookie(
        "refresh_token",
        domain=settings.CIASTECZKO_ODSWIEZANIA_DOMENA,
        path="/api/accounts/",
        samesite=settings.CIASTECZKO_ODSWIEZANIA_SAMESITE,
    )
