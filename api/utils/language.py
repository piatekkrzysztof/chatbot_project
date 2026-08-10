"""
Rozpoznanie języka wiadomości odwiedzającego.

Dlaczego w kodzie, a nie w promptcie: pomiary na modelu pokazały, że instrukcja
opisująca listę dozwolonych języków ma dwa tryby awarii i przeskakuje między
nimi zależnie od sformułowania. Albo model lustrzanie dopasowuje język pytania
i ignoruje listę klienta (hiszpańskie pytanie dostaje hiszpańską odpowiedź,
choć firma obsługuje tylko polski), albo zwija wszystko do domyślnego i ignoruje
zezwolenie (angielskie pytanie dostaje polską odpowiedź mimo włączonego EN).
Stabilna była wyłącznie instrukcja wskazująca JEDEN język — dlatego wybór
języka rozstrzygamy tutaj, a model dostaje gotową, jednoznaczną decyzję.

Dlaczego bez biblioteki: nie rozpoznajemy dowolnego języka świata, tylko
rozstrzygamy między czterema obsługiwanymi (WIDGET_LANGUAGES) a "żadnym z nich".
To zadanie zamknięte i wystarczają do niego słowa funkcyjne oraz znaki
diakrytyczne. Wiadomość, której nie rozpoznamy, trafia na język domyślny —
najgorszym skutkiem błędu jest odpowiedź po polsku zamiast po angielsku,
nie odpowiedź w języku, którego firma nie obsłuży.
"""
import re

# Słowa funkcyjne, celowo krótkie listy z naciskiem na formy pytające — widget
# dostaje przede wszystkim pytania. Dobrane tak, by nie kolidowały między
# językami; kolizje (np. niemieckie i angielskie "was") rozstrzyga przewaga
# punktów z pozostałych trafień i znaki diakrytyczne.
SLOWA = {
    "pl": {
        "jakie", "jaki", "jaka", "gdzie", "ile", "kosztuje", "czy", "jest", "są",
        "macie", "mam", "chcę", "mogę", "proszę", "dziękuję", "dzień", "dobry",
        "godziny", "otwarcia", "cena", "nie", "tak", "oraz", "dla", "jak", "co",
        "kiedy", "wasz", "wasza", "wasze", "sklep", "zamówienie", "dostawa",
    },
    "en": {
        "what", "where", "when", "how", "much", "many", "your", "you", "the",
        "are", "is", "do", "does", "can", "could", "would", "have", "hours",
        "opening", "price", "cost", "please", "thanks", "thank", "hello", "hi",
        "order", "delivery", "shop", "about", "with", "for", "and", "want",
    },
    "de": {
        "wie", "wo", "wann", "was", "sind", "ist", "ihre", "ihr", "haben",
        "kann", "können", "ich", "wir", "bitte", "danke", "guten", "tag",
        "öffnungszeiten", "preis", "kostet", "und", "der", "die", "das", "für",
        "bestellung", "lieferung", "geschäft", "möchte", "einen", "eine",
    },
    "cs": {
        "jaké", "jaká", "jaký", "kde", "kdy", "kolik", "stojí", "jste", "vaše",
        "váš", "můžu", "mohu", "prosím", "děkuji", "dobrý", "den", "otevírací",
        "doba", "doprava", "objednávka", "obchod", "chci", "máte", "nemáte",
        "ceny", "zboží", "jsou", "není",
    },
    "ru": {
        "что", "где", "когда", "как", "сколько", "стоит", "вы", "ваш", "ваши",
        "есть", "можно", "пожалуйста", "спасибо", "здравствуйте", "часы",
        "работы", "цена", "доставка", "заказ", "магазин", "хочу", "это",
    },
    "uk": {
        "що", "де", "коли", "як", "скільки", "коштує", "ви", "ваш", "ваші",
        "є", "можна", "ласка", "дякую", "доброго", "години", "роботи", "ціна",
        "доставка", "замовлення", "магазин", "хочу", "це",
    },
}

# Znaki występujące praktycznie wyłącznie w danym języku z obsługiwanej szóstki.
# Polskie "ó" pomijamy — jest też w czeskim i hiszpańskim. Czeskie "ř/ů/ě"
# i polskie "ą/ć/ę/ł/ń/ś/ź/ż" rozdzielają te dwa języki mimo wspólnych słów.
DIAKRYTYKI = {
    "pl": set("ąćęłńśźż"),
    "de": set("äöüß"),
    "cs": set("řůěťďň"),
    # Ukraińskie і/ї/є/ґ nie występują w rosyjskim, a rosyjskie ы/ъ/э/ё
    # w ukraińskim — to najpewniejszy sposób rozdzielenia obu cyrylic
    "uk": set("іїєґ"),
    "ru": set("ыъэё"),
}

CYRYLICA = re.compile(r"[Ѐ-ӿ]")
JEZYKI_CYRYLICKIE = ("uk", "ru")

# Poniżej tego progu uznajemy, że nie rozpoznaliśmy języka. Jedno trafienie
# bywa przypadkowe — "die" pada i po niemiecku, i w angielskim zdaniu.
PROG = 2


def wykryj_jezyk(tekst):
    """
    Kod jednego z obsługiwanych języków albo None, gdy nie rozpoznano.

    None jest pełnoprawnym wynikiem: hiszpańskie czy francuskie pytanie ma
    trafić na język domyślny firmy, a nie na siłę do najbliższego z listy.
    """
    if not tekst or not tekst.strip():
        return None

    tekst = tekst.lower()
    slowa = set(re.findall(r"\w+", tekst, flags=re.UNICODE))
    znaki = set(tekst)

    # Cyrylica zawęża wybór do dwóch języków, ale sama w sobie nie rozstrzyga —
    # wcześniej każdy tekst cyrylicki szedł na ukraiński, więc rosyjskojęzyczny
    # odwiedzający dostawał odpowiedź po ukraińsku.
    kandydaci = JEZYKI_CYRYLICKIE if CYRYLICA.search(tekst) else tuple(
        kod for kod in SLOWA if kod not in JEZYKI_CYRYLICKIE
    )

    punkty = {kod: len(slowa & SLOWA[kod]) for kod in kandydaci}
    for kod in kandydaci:
        if znaki & DIAKRYTYKI.get(kod, set()):
            # Diakrytyk to mocna przesłanka, ale sam w sobie nie przesądza —
            # niemieckie "ö" pada w cytowanej nazwie własnej w polskim zdaniu
            punkty[kod] += 2

    najlepszy = max(punkty, key=lambda kod: punkty[kod])

    # Remis oznacza, że przesłanki są sprzeczne — lepiej oddać decyzję domyślnemu
    if list(punkty.values()).count(punkty[najlepszy]) > 1:
        return None

    if punkty[najlepszy] < PROG:
        # Sam alfabet to już mocna przesłanka: tekst cyrylicki na pewno nie jest
        # polski ani niemiecki, więc przy jednym trafieniu nadal warto zgadywać
        if CYRYLICA.search(tekst) and punkty[najlepszy] >= 1:
            return najlepszy
        return None

    return najlepszy


def jezyk_odpowiedzi(tekst, dozwolone, domyslny=None):
    """
    Język, w którym bot ma odpowiedzieć: język pytania, jeśli firma go dopuszcza,
    w przeciwnym razie zapasowy.

    `dozwolone` to wynik Tenant.languages() — zawsze co najmniej jednoelementowy.
    `domyslny` to Tenant.default_language(); bez niego bierzemy pierwszy z listy.
    """
    wykryty = wykryj_jezyk(tekst)
    if wykryty and wykryty in dozwolone:
        return wykryty
    return domyslny or dozwolone[0]
