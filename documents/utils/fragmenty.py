"""
Dzielenie dokumentu na fragmenty do wyszukiwania semantycznego.

Poprzednia wersja wołała `textwrap.wrap(tresc, 500)`. To zawijarka wierszy,
nie dzielarka tekstu, i domyślnie zgniata wszystkie białe znaki — czyli
kasuje akapity i nagłówki, zanim cokolwiek zdąży je wykorzystać. Typowa
oferta wyglądała po niej tak:

    OFERTA WESELNA Sala Debowa miesci 120 osob. Cena w sobote 4500 zl ...
    ... liczba gosci to 20. Menu ustalamy indywidualnie.  NOCLEGI Dysponujemy
    | 14 pokojami dla 40 gosci. Doba hotelowa 180 zl od pokoju ...

Dwie szkody widać wprost. Nagłówek "NOCLEGI" kończy jeden fragment, a jego
treść zaczyna następny — pytanie o cenę noclegu nie trafia dobrze w żaden.
I jeden fragment miesza wesela, menu, chrzciny oraz początek noclegów, więc
jego wektor jest uśrednieniem czterech tematów, zdominowanym przez ten,
którego jest najwięcej. Stąd brało się to, że pytanie o chrzciny wyciągało
"fragmenty o weselach": w tym samym kawałku tekstu naprawdę były oba.

Tutaj tniemy po granicach, które w tekście już są — akapitach i nagłówkach —
i dopiero w ich ramach pilnujemy długości.
"""
import re

# Górna granica fragmentu. Krótsze fragmenty dają ostrzejsze dopasowanie, ale
# rozbijają cenniki i wyliczenia; dłuższe rozmywają wektor. 1200 znaków to
# mniej więcej akapit z nagłówkiem — na tyle dużo, żeby zmieścić pozycję
# cennika razem z jej ceną, i na tyle mało, żeby nie mieszać dwóch usług.
MAKS_ZNAKOW = 1200

# Ile znaków końca poprzedniego fragmentu powtarzamy na początku następnego.
# Bez tego fakt przecięty granicą przepada: ani "Doba hotelowa" nie wie o cenie,
# ani cena o tym, czego dotyczy.
ZAKLADKA = 180

# Wiersz krótszy niż tyle znaków, bez kropki na końcu, traktujemy jak nagłówek
# sekcji i doklejamy do każdego fragmentu, który z tej sekcji pochodzi.
MAKS_DLUGOSC_NAGLOWKA = 80

_KONIEC_ZDANIA = re.compile(r"(?<=[.!?])\s+")


def _czy_naglowek(blok):
    """
    Krótki, jednowierszowy blok bez kropki na końcu — czyli nagłówek sekcji.

    Rozpoznanie jest heurystyczne i takie zostaje: pomyłka w jedną stronę
    dokleja niepotrzebne zdanie do kilku fragmentów, w drugą — gubi kontekst.
    Obie są znośne, w odróżnieniu od poprzedniego stanu, w którym nagłówek
    lądował w innym fragmencie niż treść, której dotyczy.
    """
    if "\n" in blok or len(blok) > MAKS_DLUGOSC_NAGLOWKA:
        return False
    return not blok.rstrip().endswith((".", "!", "?", ":", ";", ","))


def _bloki(tresc):
    """Akapity dokumentu — puste wiersze są granicą, którą autor już postawił."""
    for surowy in re.split(r"\n\s*\n", tresc):
        blok = "\n".join(w.strip() for w in surowy.splitlines() if w.strip())
        if blok:
            yield blok


def _potnij_dlugi_blok(blok, limit):
    """
    Awaryjne cięcie akapitu, który sam w sobie przekracza limit.

    Najpierw po zdaniach, bo tam przebiega naturalna granica sensu. Zdanie
    dłuższe niż limit (zdarza się w regulaminach) tniemy po słowach — brzydko,
    ale nie gubiąc znaków.
    """
    czesci, biezaca = [], ""
    for zdanie in _KONIEC_ZDANIA.split(blok):
        if not zdanie:
            continue
        if len(biezaca) + len(zdanie) + 1 <= limit:
            biezaca = f"{biezaca} {zdanie}".strip()
            continue
        if biezaca:
            czesci.append(biezaca)
        while len(zdanie) > limit:
            ciecie = zdanie.rfind(" ", 0, limit)
            if ciecie <= 0:
                ciecie = limit
            czesci.append(zdanie[:ciecie].strip())
            zdanie = zdanie[ciecie:].strip()
        biezaca = zdanie
    if biezaca:
        czesci.append(biezaca)
    return czesci


def _ogon(tekst, ile):
    """Końcówka fragmentu na zakładkę, urwana na granicy słowa."""
    if len(tekst) <= ile:
        return tekst
    wycinek = tekst[-ile:]
    spacja = wycinek.find(" ")
    return wycinek[spacja + 1:] if spacja != -1 else wycinek


def podziel_na_fragmenty(tresc, maks_znakow=MAKS_ZNAKOW, zakladka=ZAKLADKA):
    """
    Fragmenty gotowe do policzenia wektora. Zwraca listę napisów.

    Zasada: nigdy nie łamiemy akapitu, dopóki mieści się w limicie. Nagłówek
    sekcji wędruje z każdym fragmentem tej sekcji. Sąsiednie fragmenty zachodzą
    na siebie zakładką.
    """
    if not tresc or not tresc.strip():
        return []

    fragmenty = []
    naglowek = ""
    biezaca = ""

    def domknij():
        nonlocal biezaca
        if biezaca.strip():
            fragmenty.append(biezaca.strip())
        biezaca = ""

    def zacznij_nowa():
        """Nowy fragment startuje od nagłówka sekcji i zakładki z poprzedniego."""
        czesci = []
        if naglowek:
            czesci.append(naglowek)
        if fragmenty and zakladka:
            ogon = _ogon(fragmenty[-1], zakladka)
            # Nagłówek bywa już w ogonie poprzedniego fragmentu — nie dublujemy
            if ogon and ogon != naglowek:
                czesci.append(ogon)
        return "\n".join(czesci)

    for blok in _bloki(tresc):
        if _czy_naglowek(blok):
            # Nowa sekcja zaczyna nowy fragment: mieszanie dwóch sekcji w jednym
            # wektorze jest dokładnie tym, co psuło wyszukiwanie.
            domknij()
            naglowek = blok
            biezaca = naglowek
            continue

        for czesc in _potnij_dlugi_blok(blok, maks_znakow) if len(blok) > maks_znakow else [blok]:
            if biezaca and len(biezaca) + len(czesc) + 1 > maks_znakow:
                domknij()
                biezaca = zacznij_nowa()
            biezaca = f"{biezaca}\n{czesc}".strip() if biezaca else czesc

    domknij()

    # Fragment złożony z samego nagłówka nic nie wnosi, a zaśmieca wyniki
    return [f for f in fragmenty if f and f != naglowek or "\n" in f]


def tekst_do_wektora(fragment, nazwa_dokumentu):
    """
    Co naprawdę idzie do modelu embeddingów.

    Nazwa dokumentu wchodzi do wektora, ale NIE do zapisanej treści: w prompcie
    jest dodawana osobno (`[Źródło: ...]`), więc w treści byłaby powtórzeniem.
    Tutaj daje wektorowi kontekst, którego sam fragment nie niesie — "180 zł
    od pokoju" znaczy co innego w cenniku hotelu niż w regulaminie parkingu.
    """
    nazwa = (nazwa_dokumentu or "").strip()
    return f"{nazwa}\n\n{fragment}" if nazwa else fragment
