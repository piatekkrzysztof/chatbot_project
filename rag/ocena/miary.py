"""
Miary jakości wyszukiwania.

Jedna liczba nie wystarczy i to jest tu najważniejsza decyzja. Wyszukiwarka,
która na każde pytanie oddaje pięć najbliższych fragmentów, ma trafność bliską
stu procent - i jest bezużyteczna, bo na pytanie o stolicę Australii cytuje
cennik przeglądów. Wyszukiwarka, która nie oddaje nigdy niczego, ma zerowy
odsetek fałszywych trafień i jest bezużyteczna tak samo.

Dlatego liczymy dwie rzeczy osobno i obie muszą się trzymać progu:

  • trafnosc  - czy znajduje, gdy JEST co znaleźć,
  • cisza     - czy milczy, gdy NIE MA czego znaleźć.

Zmiana progu odległości przesuwa te dwie miary w przeciwne strony. Widać to
dopiero wtedy, gdy patrzy się na obie naraz - jedna liczba pozwoliłaby
„poprawić wynik", psując produkt.
"""

from dataclasses import dataclass

from rag.ocena.korpus import Pytanie


@dataclass(frozen=True)
class WynikPytania:
    pytanie: Pytanie
    znalezione: tuple[str, ...]
    """Klucze fragmentów w kolejności od najbliższego."""

    @property
    def trafione(self) -> bool:
        """Czy oczekiwany fragment znalazł się gdziekolwiek w wynikach."""
        return bool(self.pytanie.oczekiwane & set(self.znalezione))

    @property
    def pozycja(self) -> int | None:
        """
        Miejsce pierwszego trafnego fragmentu, licząc od 1.

        Pozycja ma znaczenie, bo do modelu trafia ograniczona liczba
        fragmentów, a te dalsze giną w szumie bliższych. Fragment znaleziony
        na piątym miejscu jest wyraźnie gorszy niż ten sam na pierwszym.
        """
        for numer, klucz in enumerate(self.znalezione, start=1):
            if klucz in self.pytanie.oczekiwane:
                return numer
        return None

    @property
    def zamilkl(self) -> bool:
        return not self.znalezione


@dataclass(frozen=True)
class Ocena:
    trafnosc: float
    """Odsetek pytań z odpowiedzią, dla których znaleziono właściwy fragment."""

    trafnosc_na_pierwszym: float
    """Odsetek pytań z odpowiedzią, gdzie właściwy fragment był NAJBLIŻSZY."""

    srednia_odwrotna_pozycja: float
    """MRR - im bliżej 1, tym wyżej w wynikach ląduje właściwy fragment."""

    cisza: float
    """Odsetek pytań BEZ odpowiedzi, przy których nic nie przeszło przez próg."""

    liczba_z_odpowiedzia: int
    liczba_bez_odpowiedzi: int

    def jako_wiersze(self) -> list[str]:
        return [
            f"trafnosc                 {self.trafnosc:6.1%}  "
            f"(pytan z odpowiedzia: {self.liczba_z_odpowiedzia})",
            f"  w tym na 1. miejscu    {self.trafnosc_na_pierwszym:6.1%}",
            f"  srednia odwrotna poz.  {self.srednia_odwrotna_pozycja:6.3f}",
            f"cisza                    {self.cisza:6.1%}  "
            f"(pytan bez odpowiedzi: {self.liczba_bez_odpowiedzi})",
        ]


def policz(wyniki: list[WynikPytania]) -> Ocena:
    z_odpowiedzia = [w for w in wyniki if w.pytanie.ma_odpowiedz]
    bez_odpowiedzi = [w for w in wyniki if not w.pytanie.ma_odpowiedz]

    if not z_odpowiedzia:
        raise ValueError(
            "Zestaw nie zawiera zadnego pytania z oczekiwana odpowiedzia - nie ma czego mierzyc."
        )
    if not bez_odpowiedzi:
        raise ValueError(
            "Zestaw nie zawiera pytan bez odpowiedzi. Bez nich mierzylibysmy "
            "wylacznie trafnosc, czyli nagradzali wyszukiwarke, ktora zawsze "
            "cos zwraca."
        )

    trafione = [w for w in z_odpowiedzia if w.trafione]
    na_pierwszym = [w for w in z_odpowiedzia if w.pozycja == 1]
    odwrotne = [1 / w.pozycja for w in z_odpowiedzia if w.pozycja]

    return Ocena(
        trafnosc=len(trafione) / len(z_odpowiedzia),
        trafnosc_na_pierwszym=len(na_pierwszym) / len(z_odpowiedzia),
        srednia_odwrotna_pozycja=sum(odwrotne) / len(z_odpowiedzia),
        cisza=len([w for w in bez_odpowiedzi if w.zamilkl]) / len(bez_odpowiedzi),
        liczba_z_odpowiedzia=len(z_odpowiedzia),
        liczba_bez_odpowiedzi=len(bez_odpowiedzi),
    )


def opisz_bledy(wyniki: list[WynikPytania]) -> list[str]:
    """
    Wypisuje, co konkretnie poszło nie tak.

    Sama liczba mówi, że jest gorzej, ale nie mówi, którym pytaniom się to
    stało - a bez tego nie da się zdecydować, czy zmiana jest do przyjęcia.
    """
    linie = []

    for wynik in wyniki:
        if wynik.pytanie.ma_odpowiedz and not wynik.trafione:
            oczekiwane = ", ".join(sorted(wynik.pytanie.oczekiwane))
            znalezione = ", ".join(wynik.znalezione) or "nic"
            linie.append(
                f"  NIE ZNALAZL  [{wynik.pytanie.grupa}] {wynik.pytanie.tresc}"
                f"\n      oczekiwano: {oczekiwane}\n      dostal:     {znalezione}"
            )
        elif not wynik.pytanie.ma_odpowiedz and not wynik.zamilkl:
            linie.append(
                f"  NIE ZAMILKL  [{wynik.pytanie.grupa}] {wynik.pytanie.tresc}"
                f"\n      przepuscil: {', '.join(wynik.znalezione)}"
            )

    return linie
