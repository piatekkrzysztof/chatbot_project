"""
Sprowadzanie adresu e-mail do skrzynki, do której naprawdę trafia poczta.

Po co
-----
Okres próbny przysługuje adresowi: potwierdzenie e-maila daje 14 dni i 2000
wiadomości. Adresów tej samej skrzynki jest jednak wiele. `jan+sklep@gmail.com`,
`jan+bot@gmail.com` i `j.a.n@gmail.com` to jedno pudełko i jeden człowiek,
a dla systemu to trzy różne konta i trzy okresy próbne. Przy zmierzonym koszcie
krańcowym jeden taki okres to 6-10 zł naszych pieniędzy wydanych u OpenAI.

Czego to NIE robi
-----------------
**Nie blokuje niczego.** Wynik tej funkcji służy wyłącznie do rozpoznania, że
warto się przyjrzeć - konto powstaje normalnie i okres próbny też. Decyzja
właściciela z 29.09.2026: najpierw zobaczmy, czy to się w ogóle zdarza.

Ma to konsekwencję dla progu ostrożności. Gdyby wynik odmawiał czegokolwiek,
każde fałszywe trafienie kosztowałoby uczciwego klienta, więc normalizacja
musiałaby być zachowawcza. Skoro wynik tylko zapala lampkę, może być bardziej
stanowcza - fałszywe trafienie kosztuje jedno spojrzenie człowieka.

Dlaczego kropki tylko w Gmailu
------------------------------
Znacznik po `+` to konwencja (RFC 5233) używana w zasadzie wyłącznie świadomie
i wyłącznie przez właściciela skrzynki, więc obcinamy go wszędzie. Kropki są
inne: `j.an@` i `jan@` to jedna skrzynka w Gmailu, ale **dwie różne** u
większości pozostałych dostawców. Obcinanie ich poza Gmailem sklejałoby konta
dwóch obcych osób.
"""

import hashlib

from django.conf import settings

#: Domeny, które są tym samym dostawcą pod inną nazwą.
ALIASY_DOMEN = {
    "googlemail.com": "gmail.com",
}

#: Dostawcy ignorujący kropki w części lokalnej.
DOMENY_BEZ_KROPEK = {"gmail.com"}


def normalizuj(adres):
    """
    Adres sprowadzony do skrzynki. Pusty ciąg, gdy to nie wygląda na adres.

    Nie waliduje adresu - od tego jest formularz rejestracji. Tutaj chodzi
    wyłącznie o to, żeby dwa zapisy tej samej skrzynki dały ten sam wynik.
    """
    if not adres or "@" not in adres:
        return ""
    lokalna, _, domena = adres.strip().lower().rpartition("@")
    if not lokalna or not domena:
        return ""

    domena = ALIASY_DOMEN.get(domena, domena)
    lokalna = lokalna.split("+", 1)[0]
    if domena in DOMENY_BEZ_KROPEK:
        lokalna = lokalna.replace(".", "")
    if not lokalna:
        # Adres w rodzaju "+tag@gmail.com": po obcięciu nie zostaje nic,
        # z czym dałoby się cokolwiek porównać.
        return ""
    return f"{lokalna}@{domena}"


def skrot_skrzynki(adres):
    """
    Nieodwracalny skrót znormalizowanego adresu. Pusty ciąg, gdy brak adresu.

    Zapisujemy skrót, nie adres. Do rozpoznania powtórki wystarczy porównanie
    równości, a drugi adres e-mail obok istniejącego `owner_email` byłby
    kopią danych osobowych trzymaną wyłącznie na wszelki wypadek. Ten sam
    zabieg stosują już limity rejestracji dla adresów IP.
    """
    znormalizowany = normalizuj(adres)
    if not znormalizowany:
        return ""
    # Klucz Django jako sól: skrót nie daje się porównać z niczym spoza tej
    # instalacji, więc nie wyniesie się go do innej bazy i nie sprawdzi słownikiem.
    return hashlib.sha256(f"{settings.SECRET_KEY}:skrzynka:{znormalizowany}".encode()).hexdigest()
