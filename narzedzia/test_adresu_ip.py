"""
Czy serwer rozpoznaje prawdziwy adres odwiedzającego i nie da się go podrobić.

Odbiór F23/punkt 2G. Limity (20 wiadomości na godzinę na odwiedzającego,
5 zgłoszeń z formularza) liczą się po adresie IP. Serwer bierze go z nagłówka
X-Forwarded-For, ale ufa tylko TRUSTED_PROXY_DEPTH ostatnim wpisom - tym
dopisanym przez własne proxy Rendera. Gdyby ufał więcej, każdy obszedłby limit,
wysyłając w nagłówku zmyślony adres.

Skrypt loguje się na podane konto, pyta /api/diagnostyka/adres/ raz normalnie
i kilka razy z podrobionym nagłówkiem, a na końcu się wylogowuje. Rozpoznany
adres musi być we wszystkich próbach ten sam - i równy temu, co pokazuje
„jaki mam IP” w przeglądarce na tym samym komputerze.

    python narzedzia/test_adresu_ip.py https://ADRES-BACKENDU https://ADRES-PANELU

Tylko biblioteka standardowa Pythona. Hasło wpisujesz w terminalu (nie jest
widoczne ani zapisywane), token nie jest wypisywany. Uruchamiaj na koncie
testowym, nie na koncie klienta.
"""

import getpass
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

PODROBIONE = [
    "203.0.113.66",  # adres z puli dokumentacyjnej - nie należy do nikogo
    "203.0.113.66, 198.51.100.7",
    "1.1.1.1, 203.0.113.66, 198.51.100.7, 192.0.2.1",
]


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    api = sys.argv[1].rstrip("/") + "/api"
    panel = sys.argv[2].rstrip("/")
    ciasteczka = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def wyslij(metoda, sciezka, dane=None, naglowki=None):
        zadanie = urllib.request.Request(
            api + sciezka,
            data=json.dumps(dane).encode() if dane is not None else None,
            method=metoda,
            headers={"Content-Type": "application/json", "Origin": panel, **(naglowki or {})},
        )
        try:
            with ciasteczka.open(zadanie, timeout=30) as odpowiedz:
                return odpowiedz.status, json.loads(odpowiedz.read() or b"{}")
        except urllib.error.HTTPError as blad:
            return blad.code, json.loads(blad.read() or b"{}")

    email = input("E-mail konta testowego: ").strip()
    haslo = getpass.getpass("Hasło (niewidoczne): ")
    status, dane = wyslij("POST", "/accounts/login/", {"username": email, "password": haslo})
    del haslo
    if status == 200 and dane.get("wymaga_drugiego_skladnika"):
        kod = input("Kod z aplikacji uwierzytelniającej: ").strip()
        status, dane = wyslij("POST", "/accounts/login/2fa/", {"bilet": dane["bilet"], "kod": kod})
    if status != 200 or "access" not in dane:
        print(f"Logowanie nieudane ({status}): {dane.get('error') or dane.get('detail') or dane}")
        sys.exit(1)
    token = {"Authorization": f"Bearer {dane['access']}"}

    try:
        status, wzor = wyslij("GET", "/diagnostyka/adres/", naglowki=token)
        if status != 200:
            print(f"Diagnostyka niedostępna ({status}): {wzor}")
            sys.exit(1)
        prawdziwy = wzor["rozpoznany_adres"]
        print()
        print(f"TRUSTED_PROXY_DEPTH na serwerze: {wzor['trusted_proxy_depth']}")
        print(f"Bez podrabiania serwer widzi:     {prawdziwy}")
        print(f"  (łańcuch X-Forwarded-For: {', '.join(wzor['x_forwarded_for']) or 'brak'})")
        print()

        podrobiony_przeszedl = False
        for naglowek in PODROBIONE:
            status, wynik = wyslij(
                "GET", "/diagnostyka/adres/", naglowki={**token, "X-Forwarded-For": naglowek}
            )
            rozpoznany = wynik.get("rozpoznany_adres")
            dobrze = status == 200 and rozpoznany == prawdziwy
            podrobiony_przeszedl |= not dobrze
            werdykt = "OK   " if dobrze else "BŁĄD "
            print(f"{werdykt} podrobione „{naglowek}” -> serwer widzi {rozpoznany}")
    finally:
        wyslij("POST", "/accounts/logout/", {}, naglowki=token)

    print()
    if podrobiony_przeszedl:
        print("WYNIK: NIE ZALICZONE. Podrobiony nagłówek zmienia rozpoznany adres - limity")
        print("da się obejść. TRUSTED_PROXY_DEPTH jest za duże; wklej ten wynik.")
        sys.exit(1)
    print("WYNIK: podrabianie nie działa.")
    print(f"Sprawdź jeszcze, czy {prawdziwy} to Twój adres: wpisz w przeglądarce")
    print("„jaki mam IP”. Jeśli się zgadza - odbiór zaliczony. Jeśli serwer widzi inny")
    print("adres (np. adres Rendera), TRUSTED_PROXY_DEPTH jest za małe; wklej ten wynik.")


if __name__ == "__main__":
    main()
