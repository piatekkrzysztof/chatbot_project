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

# Ile treści musi iść PO krótkiej linii, żeby uznać ją za nagłówek sekcji.
# Bez tego warunku każde hasło ze strony sprzedażowej zaczynało nowy fragment.
#
# 60 znaków, a nie więcej, i to jest zmierzone: przy 90 przestaje działać
# rozdzielanie krótkich sekcji cennika, czyli to, po co ten mechanizm powstał.
# Sekcja "CHRZCINY I KOMUNIE" ma pod sobą jedno zdanie i musi zostać osobnym
# fragmentem, inaczej wraca problem wektora uśredniającego kilka usług.
MIN_TRESCI_POD_NAGLOWKIEM = 60

# Fragment krótszy niż tyle znaków nie jest sensowną jednostką wyszukiwania:
# jego wektor niesie zbyt mało, żeby cokolwiek znaczyć, a policzenie kosztuje
# tyle samo, co pełnego. Takie doklejamy do sąsiada, nie kasujemy — treść ma
# nie ginąć, nawet drobna.
#
# Nisko celowo. Wyższy próg sklejał z powrotem krótkie sekcje cennika, czyli
# odwracał robotę podziału. Chodzi wyłącznie o resztki w rodzaju "→" albo
# "Zobacz projekty", nie o zwięzłe sekcje.
MIN_DLUGOSC_FRAGMENTU = 40

_KONIEC_ZDANIA = re.compile(r"(?<=[.!?])\s+")

# Linia oddzielająca nagłówek tabeli Markdown od treści: |---|:---:|
_SEPARATOR_MARKDOWN = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")

# Tabela, której wiersze dostają własne fragmenty: nagłówek i co najmniej dwa
# wiersze danych. Przy jednym wierszu fragment tabeli jest już o nim.
MIN_WIERSZY_TABELI = 2


def _czy_naglowek(blok, nastepny=""):
    """
    Krótki blok bez kropki na końcu, po którym idzie realna treść.

    Warunek „po którym idzie realna treść" dopisany po pomiarze na prawdziwej
    stronie sprzedażowej. Bez niego heurystyka uznawała za nagłówek 36% bloków:
    tekst marketingowy to w większości krótkie linie bez kropek („Umów
    bezpłatną rozmowę", „Zobacz projekty", „→"). Każda zaczynała nowy fragment,
    więc z 9 280 znaków robiło się 58 fragmentów — w tym takie o długości
    jednego znaku.

    Nagłówek to tytuł NAD czymś. Jeśli po krótkiej linii idzie druga równie
    krótka, to nie tytuł, tylko po prostu krótkie zdanie.
    """
    if "\n" in blok or len(blok) > MAKS_DLUGOSC_NAGLOWKA:
        return False
    if blok.rstrip().endswith((".", "!", "?", ":", ";", ",")):
        return False
    return len(nastepny) >= MIN_TRESCI_POD_NAGLOWKIEM


# Znaki sterujące z ekstrakcji PDF-a (np. wypunktowanie odczytane jako \x7f).
# Trafiały do treści fragmentu i do podglądu w panelu.
_ZNAKI_STERUJACE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NUMER_SEKCJI = re.compile(r"^\d+[.)]?\s+\S")
_WYPUNKTOWANIE = ("•", "-", "–", "*", "·")


def _zaczyna_tresc(linia):
    """Czy linia może być początkiem nowej treści, a nie dalszym ciągiem zdania."""
    return linia[0].isupper() or linia[0].isdigit() or linia.startswith(_WYPUNKTOWANIE)


def _moze_byc_naglowkiem(linia):
    """
    Wstępne sito. Kropkę na końcu i minimalną treść pod spodem sprawdza
    potem `_czy_naglowek` - tu tylko to, czego on nie wie: wiersz tabeli
    (nagłówek tabeli zostaje w sekcji, pod którą stoi) i początek linii.
    """
    if not 3 <= len(linia) <= MAKS_DLUGOSC_NAGLOWKA or " | " in linia:
        return False
    return linia[0].isupper() or bool(_NUMER_SEKCJI.match(linia))


def _wydziel_naglowki(tresc):
    """
    Otacza pustymi liniami nagłówki sekcji, przed którymi ich nie ma.

    Podział szuka granic po pustych liniach. Tekst z PDF-a i DOCX-a ich nie ma:
    akapity są oddzielone pojedynczym znakiem nowej linii. Odbiór 8.10.2026:
    trzystronicowa oferta z PDF-a dała trzy fragmenty - po jednym na stronę,
    z dwiema albo trzema sekcjami w każdym. Pytanie o anulowanie leżało od
    fragmentu „anulowanie + płatność + kontakt" o 1,02 przy progu 0,96.

    Nagłówek to tu linia, która spełnia naraz cztery warunki: krótka, bez
    kropki na końcu i bez kresek tabeli; zaczyna się wielką literą albo
    numerem; POPRZEDNIA linia kończy zdanie; NASTĘPNA zaczyna się wielką
    literą, cyfrą albo wypunktowaniem. Dwa ostatnie odsiewają komórki tabel
    z PDF-a („Bufet Premium" po „przekąski" bez kropki) i linie łamane
    w połowie zdania. Czy linia faktycznie zostanie nagłówkiem, rozstrzyga
    dalej `_czy_naglowek` - tu tylko dostaje szansę.
    """
    linie = [linia.strip() for linia in tresc.splitlines()]
    # Następna niepusta linia dla każdej pozycji - jeden przebieg od końca,
    # bo dokument ma do 2 mln znaków, czyli dziesiątki tysięcy linii.
    nastepne = [""] * len(linie)
    kolejna = ""
    for numer in range(len(linie) - 1, -1, -1):
        nastepne[numer] = kolejna
        if linie[numer]:
            kolejna = linie[numer]

    wynik = []
    poprzednia = ""
    for numer, linia in enumerate(linie):
        nastepna = nastepne[numer]
        naglowek = (
            bool(linia)
            and _moze_byc_naglowkiem(linia)
            and (not poprzednia or poprzednia.endswith((".", "!", "?", ":")))
            and bool(nastepna)
            and _zaczyna_tresc(nastepna)
        )
        if naglowek and wynik and wynik[-1]:
            wynik.append("")
        wynik.append(linia)
        if naglowek:
            wynik.append("")
        if linia:
            poprzednia = linia
    return "\n".join(wynik)


def _bloki(tresc):
    """Akapity dokumentu — puste wiersze są granicą, którą autor już postawił."""
    tresc = _wydziel_naglowki(_ZNAKI_STERUJACE.sub("", tresc))
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
    return wycinek[spacja + 1 :] if spacja != -1 else wycinek


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

    # Lista, nie generator: rozpoznanie nagłówka wymaga podejrzenia, co idzie
    # po nim — bez tego każde hasło ze strony sprzedażowej byłoby nagłówkiem.
    bloki = list(_bloki(tresc))

    for numer, blok in enumerate(bloki):
        nastepny = bloki[numer + 1] if numer + 1 < len(bloki) else ""
        if _czy_naglowek(blok, nastepny):
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
    fragmenty = [f for f in fragmenty if f and f != naglowek or "\n" in f]
    fragmenty = _sklej_krotkie(fragmenty, maks_znakow)
    return fragmenty + [w for w in fragmenty_wierszy_tabel(tresc) if w not in fragmenty]


def _sklej_krotkie(fragmenty, maks_znakow):
    """
    Dokleja zbyt krótkie fragmenty do sąsiada.

    Fragment o długości jednego znaku („→") nie jest jednostką wyszukiwania:
    jego wektor nie niesie nic, a policzenie kosztuje tyle samo, co pełnego.
    Doklejamy zamiast kasować, bo treść ma nie ginąć — nawet drobna.
    """
    wynik = []
    for fragment in fragmenty:
        zbyt_krotki = len(fragment) < MIN_DLUGOSC_FRAGMENTU
        zmiesci_sie = wynik and len(wynik[-1]) + len(fragment) + 1 <= maks_znakow
        if zbyt_krotki and zmiesci_sie:
            wynik[-1] = f"{wynik[-1]}\n{fragment}"
        else:
            wynik.append(fragment)
    return wynik


def _komorki(linia):
    """Komórki wiersza tabeli albo None, gdy linia nie jest wierszem tabeli."""
    linia = linia.strip()
    if " | " not in linia and not (linia.startswith("|") and linia.endswith("|")):
        return None
    komorki = [k.strip() for k in linia.strip("|").split("|")]
    return komorki if len(komorki) >= 2 and any(komorki) else None


def fragmenty_wierszy_tabel(tresc):
    """
    Każdy wiersz danych tabeli jako osobny fragment, z nagłówkiem tabeli.

    Odbiór 7.10.2026: cennik z DOCX (osiem pozycji w tabeli) trafiał do jednego
    fragmentu. Pytanie o jedną pozycję leżało od niego o 0,98 przy progu 0,96,
    a bot odpowiadał „nie posiadam informacji", choć cena była w dokumencie.
    Wektor fragmentu o ośmiu usługach jest uśrednieniem ośmiu tematów - ten sam
    problem, przed którym chroni cięcie po sekcjach, tylko wewnątrz tabeli.
    Pomiar na sześciu pytaniach o pozycje: cały cennik 2 z 6 pod progiem,
    nagłówek z wierszem 4 z 6. Resztę łapie dopasowanie po słowach
    (rag/engine.py).

    Fragment tabeli zostaje obok, więc pytanie o cały cennik działa jak dotąd.
    Nagłówek wchodzi do fragmentu, bo bez niego „Pakiet S | 99 zł | 199 zł"
    nie mówi modelowi, która cena jest netto, a która brutto.
    """
    if not tresc:
        return []
    wynik = []

    def zamknij(tabela):
        if len(tabela) < 1 + MIN_WIERSZY_TABELI:
            return
        naglowek, *wiersze = tabela
        wynik.extend(f"{naglowek}\n{wiersz}" for wiersz in wiersze)

    tabela = []
    liczba_kolumn = None
    for surowa in tresc.splitlines():
        linia = surowa.strip()
        if tabela and _SEPARATOR_MARKDOWN.match(linia):
            continue
        komorki = _komorki(linia)
        if komorki is None or (tabela and len(komorki) != liczba_kolumn):
            zamknij(tabela)
            tabela, liczba_kolumn = [], None
            if komorki is None:
                continue
        tabela.append(" | ".join(komorki))
        liczba_kolumn = len(komorki)
    zamknij(tabela)
    return list(dict.fromkeys(wynik))


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
