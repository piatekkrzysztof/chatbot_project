"""
Budżet tokenów wejściowych.

Prompt rósł bez żadnego ograniczenia: opis firmy, regulamin, do dwudziestu wpisów
FAQ, pięć fragmentów dokumentów i dziesięć wiadomości historii. Klient z obszernym
regulaminem potrafił wygenerować prompt kosztujący wielokrotnie więcej niż sama
odpowiedź, a płacimy za każdy token wejściowy przy każdej wiadomości.

Liczymy szacunkowo, bez tiktoken. Biblioteka jest wprawdzie w środowisku, ale
tylko jako zależność przechodnia openai — poleganie na takiej już raz wywróciło
produkcję (lxml_html_clean). Do tego pobiera pliki kodowania z sieci przy pierwszym
użyciu, a dysk na Renderze jest efemeryczny, więc działoby się to po każdym deployu.

Dzielnik dobrany pomiarem na tiktoken (kodowanie gpt-4o-mini) dla realnych treści:
polski wypada najgorzej — 2,83 znaku na token dla regulaminu i 2,92 dla pytania,
angielski 5,0-5,9, niemiecki 5,0, ukraiński 3,3. Przyjmujemy 2,5, czyli poniżej
najgorszego zmierzonego przypadku: szacunek zawyża liczbę tokenów, więc przycinamy
za wcześnie, nigdy za późno.
"""

ZNAKI_NA_TOKEN = 2.5

# Każda wiadomość niesie jeszcze narzut roli i separatorów formatu czatu.
# Wartość przybliżona, ale przy dziesięciu wiadomościach historii to już
# kilkadziesiąt tokenów, których nie warto ignorować.
NARZUT_NA_WIADOMOSC = 4


def oszacuj_tokeny(tekst):
    """Górne oszacowanie liczby tokenów w tekście."""
    if not tekst:
        return 0
    return int(len(tekst) / ZNAKI_NA_TOKEN) + 1


def oszacuj_tokeny_wiadomosci(messages):
    """Górne oszacowanie dla całej listy wiadomości w formacie OpenAI."""
    return sum(
        oszacuj_tokeny(wiadomosc.get("content", "")) + NARZUT_NA_WIADOMOSC
        for wiadomosc in messages
    )


def przytnij_do_budzetu(messages, budzet):
    """
    Skraca listę wiadomości tak, by zmieściła się w budżecie tokenów.

    Kolejność poświęcania jest celowa i wynika z tego, co najbardziej psuje
    odpowiedź, gdy zniknie:

    1. najstarsza historia rozmowy — bot traci pamięć dawnych zdań, ale wciąż
       rozumie bieżące pytanie,
    2. dolna część promptu systemowego, czyli wiedza o firmie — dokumenty
       i regulamin są na końcu, a zasady zachowania na górze, więc obcięcie
       od dołu zabiera wiedzę, a zostawia zakaz zmyślania.

    Nigdy nie usuwamy promptu systemowego w całości ani bieżącego pytania —
    bez nich odpowiedź nie miałaby sensu.
    """
    if not messages:
        return messages

    wiadomosci = list(messages)
    system = wiadomosci[0] if wiadomosci[0].get("role") == "system" else None
    ostatnie_pytanie = wiadomosci[-1] if len(wiadomosci) > 1 else None

    # Krok 1: wycinamy najstarszą historię, czyli wszystko poza systemem i pytaniem
    while oszacuj_tokeny_wiadomosci(wiadomosci) > budzet and len(wiadomosci) > 2:
        # indeks 1 to najstarsza wiadomość historii
        del wiadomosci[1]

    if oszacuj_tokeny_wiadomosci(wiadomosci) <= budzet or system is None:
        return wiadomosci

    # Krok 2: skracamy wiedzę w promptcie systemowym
    narzut_pytania = (
        oszacuj_tokeny(ostatnie_pytanie.get("content", "")) + NARZUT_NA_WIADOMOSC
        if ostatnie_pytanie and ostatnie_pytanie is not system
        else 0
    )
    dostepne = budzet - narzut_pytania - NARZUT_NA_WIADOMOSC
    if dostepne < 0:
        dostepne = 0

    # Odejmujemy jeszcze jeden token, bo oszacuj_tokeny zaokrągla w górę (+1).
    # Bez tego przycięty prompt wychodził dokładnie o jeden token ponad budżet.
    limit_znakow = max(0, int((dostepne - 1) * ZNAKI_NA_TOKEN))
    tresc = system.get("content", "")
    if len(tresc) > limit_znakow:
        wiadomosci[0] = {**system, "content": tresc[:limit_znakow]}

    return wiadomosci
