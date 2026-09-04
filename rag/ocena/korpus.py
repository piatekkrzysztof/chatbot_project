"""
Zestaw pomiarowy dla wyszukiwania fragmentów.

Po co to jest
-------------
Cała obietnica produktu brzmi: „bot odpowiada z Twojej bazy wiedzy". Do tej
pory nie było jak sprawdzić, czy ją spełnia - a tym bardziej, czy zmiana
w cięciu dokumentów, w progu odległości albo w modelu embeddingów jej nie
psuje. Każda taka zmiana była wprowadzana na wyczucie.

`zmierz_prog_rag` mierzy co innego: rozkład odległości na żywych danych
jednego klienta, żeby dobrać próg. Odpowiada na pytanie „czy próg pasuje do
tej firmy", nie na „czy moja zmiana pogorszyła wyszukiwanie". Tu chodzi
o to drugie, więc korpus jest stały i wynik jest porównywalny między
wersjami kodu.

Dlaczego akurat takie pytania
-----------------------------
Pytania dzielą się na cztery grupy i trzecia z czwartą są ważniejsze niż
pierwsza. Bot, który znajdzie odpowiedź na pytanie zadane słowami z dokumentu,
to niski poprzeczka. Bot, który na pytanie spoza bazy wiedzy pewnym głosem
zacytuje niezwiązany fragment, jest gorszy od takiego, który mówi „nie wiem"
- bo klient nie ma jak rozpoznać, że dostał wymyśloną odpowiedź.

Dlatego mierzymy osobno trafność (czy znajduje, gdy jest co znaleźć)
i powściągliwość (czy milczy, gdy nie ma czego znaleźć).
"""

from dataclasses import dataclass, field

#: Baza wiedzy sklepu rowerowego. Ta sama firma, która przewija się przez
#: resztę testów - łatwiej trzymać w głowie jeden przykład niż pięć.
#:
#: Fragmenty są zapisane wprost, a nie wycinane z dłuższego tekstu, bo
#: przedmiotem pomiaru jest WYSZUKIWANIE, nie cięcie. Gdyby fragmenty
#: powstawały tu z dokumentów, zmiana w dzieleniu tekstu zmieniałaby wynik
#: i nie dałoby się rozróżnić, co właściwie się pogorszyło.
FRAGMENTY: dict[str, str] = {
    "cennik-przeglad": (
        "Przeglad podstawowy roweru kosztuje 120 zl. Obejmuje regulacje "
        "hamulcow, przerzutek, centrowanie kol i smarowanie napedu."
    ),
    "cennik-lancuch": (
        "Wymiana lancucha kosztuje 80 zl plus cena czesci. Zalecamy wymiane "
        "co okolo 3000 kilometrow."
    ),
    "cennik-kolo": "Centrowanie pojedynczego kola kosztuje 60 zl.",
    "godziny": (
        "Sklep i serwis sa czynne od poniedzialku do piatku w godzinach 9-18 "
        "oraz w soboty 10-14. W niedziele nieczynne."
    ),
    "gwarancja-rama": (
        "Na ramy rowerowe udzielamy 24 miesiecy gwarancji. Gwarancja obejmuje "
        "wady materialowe i wykonania."
    ),
    "gwarancja-czesci": (
        "Czesci eksploatacyjne - lancuch, klocki hamulcowe, opony, linki - "
        "objete sa gwarancja przez 6 miesiecy."
    ),
    "dostawa-koszt": ("Wysylka kurierem kosztuje 20 zl. Odbior osobisty w sklepie jest bezplatny."),
    "dostawa-czas": "Zamowienia wysylamy w ciagu 48 godzin od zaksiegowania wplaty.",
    "serwis-termin": (
        "Standardowy czas naprawy to 3-5 dni roboczych. Przy wiekszym "
        "obciazeniu w sezonie moze sie wydluzyc do 7 dni."
    ),
    "serwis-zastepczy": (
        "Nie udostepniamy rowerow zastepczych na czas naprawy. Mozna zostawic "
        "rower na umowiony termin, zeby skrocic oczekiwanie."
    ),
}


@dataclass(frozen=True)
class Pytanie:
    """
    Jedno pytanie testowe.

    `oczekiwane` puste znaczy: nic nie powinno przejść przez próg. To NIE jest
    brak oczekiwania, tylko oczekiwanie ciszy - i jest tak samo twarde jak
    wskazanie konkretnego fragmentu.
    """

    tresc: str
    oczekiwane: frozenset[str] = field(default_factory=frozenset)
    grupa: str = ""

    @property
    def ma_odpowiedz(self) -> bool:
        return bool(self.oczekiwane)


#: Grupa 1: pytania sformulowane blisko tresci dokumentu.
#: Najlatwiejsze. Jesli tu spada trafnosc, cos jest powaznie zepsute.
WPROST = [
    Pytanie("Ile kosztuje przeglad roweru?", frozenset({"cennik-przeglad"}), "wprost"),
    Pytanie("Ile kosztuje wymiana lancucha?", frozenset({"cennik-lancuch"}), "wprost"),
    Pytanie("W jakich godzinach jestescie otwarci?", frozenset({"godziny"}), "wprost"),
    Pytanie("Ile trwa naprawa roweru?", frozenset({"serwis-termin"}), "wprost"),
    Pytanie("Ile kosztuje wysylka kurierem?", frozenset({"dostawa-koszt"}), "wprost"),
]

#: Grupa 2: to samo pytanie innymi slowami. Tak pisza prawdziwi klienci -
#: nie znaja slownictwa z dokumentu, bo go nie widzieli.
INACZEJ = [
    Pytanie("Jaka jest cena serwisu roweru?", frozenset({"cennik-przeglad"}), "inaczej"),
    Pytanie("Czy pracujecie w weekend?", frozenset({"godziny"}), "inaczej"),
    Pytanie(
        "Jak dlugo trzeba czekac na rower po oddaniu do warsztatu?",
        frozenset({"serwis-termin"}),
        "inaczej",
    ),
    Pytanie(
        "Na jak dlugo macie gwarancje na ramy?",
        frozenset({"gwarancja-rama"}),
        "inaczej",
    ),
    Pytanie(
        "Czy dostane rower na zastepstwo, kiedy moj bedzie w naprawie?",
        frozenset({"serwis-zastepczy"}),
        "inaczej",
    ),
    Pytanie("Kiedy nadacie paczke po zaplaceniu?", frozenset({"dostawa-czas"}), "inaczej"),
]

#: Grupa 3: pytania spoza jakiejkolwiek bazy wiedzy sklepu rowerowego.
#: Oczekiwana odpowiedz: CISZA. Fragment przepuszczony tutaj znaczy, ze prog
#: jest za luzny i bot bedzie cytowal cennik w odpowiedzi o stolicach.
POZA_TEMATEM = [
    Pytanie("Jaka jest stolica Australii?", grupa="poza tematem"),
    Pytanie("Kto napisal Lalke?", grupa="poza tematem"),
    Pytanie("Ile wynosi pierwiastek z dwustu piecdziesieciu szesciu?", grupa="poza tematem"),
    Pytanie("Jak zrobic zakwas na zurek?", grupa="poza tematem"),
]

#: Grupa 4: najtrudniejsza i najwazniejsza.
#:
#: Pytania z branzy, na ktore ta konkretna baza wiedzy NIE odpowiada. Sa
#: tematycznie bliskie, wiec leza blisko w przestrzeni wektorow - i to wlasnie
#: one przechodza przez zbyt luzny prog. Bot odpowiada wtedy pewnym glosem
#: cytujac cennik przegladow na pytanie o hulajnogi.
BLISKIE_ALE_NIEOBECNE = [
    Pytanie("Czy naprawiacie hulajnogi elektryczne?", grupa="bliskie, nieobecne"),
    Pytanie("Czy mozna u was kupic rower na raty?", grupa="bliskie, nieobecne"),
    Pytanie("Czy prowadzicie wypozyczalnie rowerow?", grupa="bliskie, nieobecne"),
    Pytanie("Czy robicie serwis amortyzatorow powietrznych?", grupa="bliskie, nieobecne"),
]

PYTANIA: list[Pytanie] = WPROST + INACZEJ + POZA_TEMATEM + BLISKIE_ALE_NIEOBECNE


def teksty_do_zamiany_na_wektory() -> list[str]:
    """Wszystko, co trzeba raz policzyć, w ustalonej kolejności."""
    return list(FRAGMENTY.values()) + [pytanie.tresc for pytanie in PYTANIA]
