"""
Ocena GENEROWANIA odpowiedzi - siostra oceny wyszukiwania.

Czego nie mierzy `rag/test_ocena.py`
------------------------------------
Tamta ocena mierzy, czy wyszukiwarka wyciąga właściwe fragmenty. Nie dotyka
modelu czatu, bo wektory liczy osobny model (`text-embedding-3-small`),
a `OPENAI_CHAT_MODEL` nie ma na nie żadnego wpływu.

Czyli: przy zmianie modelu czatu cały tamten przyrząd pokaże dokładnie te same
liczby, bez względu na to, czy nowy model jest lepszy, gorszy, czy w ogóle
przestał działać.

Co się psuje przy zmianie modelu
--------------------------------
`[BRAK_ODPOWIEDZI]` - znacznik, którym model mówi, że nie umie odpowiedzieć
z podanej wiedzy. Nie dociera do odwiedzającego, ale od niego zależy:

  • czy widget zaproponuje kontakt z firmą,
  • czy powstanie zapytanie i mail do właściciela,
  • raport luk w wiedzy,
  • alert o odmowach,
  • grupowanie w `zmierz_prog_rag`, czyli sposób dobierania progu.

To jest protokół, którego dotrzymuje MODEL, nie kod. Inny model może stawiać
znacznik rzadziej, częściej albo w innym miejscu - i każda z tych zmian po
cichu przestawia całą tę maszynerię. `api/tests/test_znacznik_braku_odpowiedzi.py`
sprawdza, że nasz kod poprawnie obsługuje znacznik; nie może sprawdzić, czy
prawdziwy model go wystawia.

Co jest tu prawdziwe, a co podstawione
--------------------------------------
Podstawiony jest WYŁĄCZNIE wektor pytania - bierze się z zamrożonego wzorca,
żeby wyszukiwanie było deterministyczne i darmowe. Wszystko poza tym to kod
produkcyjny: to samo zapytanie do pgvector, ten sam `build_system_prompt`,
ten sam `ObcinaczZnacznika`, to samo wywołanie modelu.

Dzięki temu dwa przebiegi na dwóch modelach różnią się wyłącznie modelem.
Liczby bezwzględne zawierają też wkład wyszukiwania; RÓŻNICA między modelami
już nie - i to ona jest podstawą decyzji.

To kosztuje prawdziwe pieniądze
-------------------------------
Każde pytanie to jedno wywołanie płatnego API, razy liczba powtórzeń. To jest
powód, dla którego nie jest to test w CI, tylko komenda uruchamiana świadomie.
"""

import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

from django.conf import settings

from api.utils.chat_engine import (
    ObcinaczZnacznika,
    build_chat_messages,
    get_openai_response,
)
from chat.models import Conversation
from rag.ocena.korpus import PYTANIA, Pytanie
from rag.ocena.przebieg import wczytaj_wzorzec, zaloz_baze_wiedzy


@dataclass(frozen=True)
class Odpowiedz:
    """Jedna odpowiedź modelu na jedno pytanie."""

    pytanie: Pytanie
    odmowil: bool
    tresc: str
    fragmentow: int
    tokenow: int
    sekund: float

    @property
    def trafil_fakt(self) -> bool | None:
        """
        Czy odpowiedź zawiera konkret z bazy wiedzy.

        None znaczy „nie da się sprawdzić", nie „nie trafił". Jedno pytanie
        w korpusie („czy dostanę rower zastępczy") ma odpowiedź przeczącą,
        więc nie ma w niej liczby ani nazwy, która by ją odróżniała od
        uprzejmej odmowy. Zaliczanie go w ciemno zawyżałoby wynik, a wliczanie
        jako porażki - zaniżało.
        """
        if self.odmowil or not self.pytanie.fakty:
            return None
        nisko = self.tresc.lower()
        return any(fakt.lower() in nisko for fakt in self.pytanie.fakty)


@dataclass(frozen=True)
class OcenaGenerowania:
    odpowiedzi: list[Odpowiedz] = field(default_factory=list)

    def _z_odpowiedzia(self):
        return [o for o in self.odpowiedzi if o.pytanie.ma_odpowiedz]

    def _bez_odpowiedzi(self):
        return [o for o in self.odpowiedzi if not o.pytanie.ma_odpowiedz]

    @property
    def odmowy_trafne(self) -> float:
        """
        Ile pytań spoza bazy wiedzy dostało znacznik. Im więcej, tym lepiej.

        To jest najważniejsza liczba w tym pomiarze. Model, który nie stawia
        znacznika, odpowiada pewnym głosem z najbliższego fragmentu - i nikt
        się o tym nie dowiaduje, bo cały mechanizm zgłaszania luk wisi na tym
        jednym ciągu znaków.
        """
        bez = self._bez_odpowiedzi()
        return sum(o.odmowil for o in bez) / len(bez) if bez else 0.0

    @property
    def odmowy_falszywe(self) -> float:
        """
        Ile pytań POKRYTYCH dostało znacznik, LICZĄC TYLKO te, którym
        wyszukiwarka faktycznie coś podała. Im mniej, tym lepiej.

        Pytania bez fragmentów są z tego wyłączone, bo model odmawia na nich
        słusznie - nie dostał czego użyć. Wliczanie ich obarczałoby model
        pudłem wyszukiwania i zmieniłoby wynik przy każdej zmianie progu,
        bez żadnej zmiany w samym modelu. Widać je osobno, w `bez_fragmentow`.
        """
        z_czego = [o for o in self._z_odpowiedzia() if o.fragmentow]
        return sum(o.odmowil for o in z_czego) / len(z_czego) if z_czego else 0.0

    @property
    def oparte_na_wiedzy(self) -> float:
        """
        Ile odpowiedzi zawiera konkret z fragmentu.

        Druga strona odmowy. Model może przestać zmyślać, stając się zarazem
        bezużytecznym: „ceny znajdzie Pan w cenniku" nie jest odmową ani
        odpowiedzią. Dla wyszukiwania to sukces - właściwy fragment wrócił.
        """
        sprawdzalne = [o for o in self.odpowiedzi if o.trafil_fakt is not None]
        return sum(o.trafil_fakt for o in sprawdzalne) / len(sprawdzalne) if sprawdzalne else 0.0

    @property
    def sprawdzalnych_faktow(self) -> int:
        return sum(1 for o in self.odpowiedzi if o.trafil_fakt is not None)

    @property
    def tokenow(self) -> int:
        return sum(o.tokenow for o in self.odpowiedzi)

    @property
    def sekund_srednio(self) -> float:
        return (
            sum(o.sekund for o in self.odpowiedzi) / len(self.odpowiedzi)
            if self.odpowiedzi
            else 0.0
        )

    @property
    def bez_fragmentow(self) -> list[Odpowiedz]:
        """Odpowiedzi na pytania pokryte, którym wyszukiwarka nic nie podała."""
        return [o for o in self._z_odpowiedzia() if o.fragmentow == 0]

    @property
    def pytania_bez_fragmentow(self) -> list[str]:
        """
        RÓŻNE pytania, którym wyszukiwarka nic nie podała.

        Nie liczba odpowiedzi: przy trzech powtórzeniach jedno pudło
        wyszukiwania daje trzy wpisy, a komunikat „3 pytania bez fragmentów"
        przy jednym prawdziwym pudle jest po prostu nieprawdą. Pierwsza wersja
        tej komendy tak właśnie pisała - i był to dokładnie ten rodzaj pomyłki,
        którego szuka reszta tego pliku, tyle że we własnym przyrządzie.

        To NIE jest wina modelu. Mówi o wyszukiwaniu, więc stoi osobno od
        liczb opisujących model.
        """
        return list(dict.fromkeys(o.pytanie.tresc for o in self.bez_fragmentow))


def _wektor_pytania(wzorzec, pytanie):
    odpowiedz = MagicMock()
    odpowiedz.data = [MagicMock(embedding=wzorzec["pytania"][pytanie.tresc])]
    return odpowiedz


def zapytaj(firma, pytanie, wzorzec, model=None, temperatura=...) -> Odpowiedz:
    """
    Jedno pytanie przez prawdziwą ścieżkę czatu, z zamrożonym wektorem.

    Rozmowa jest zakładana od nowa dla każdego pytania. Bez tego model widzi
    poprzednie odpowiedzi jako historię i drugie pytanie zadaje się w innym
    kontekście niż pierwsze - a wtedy kolejność pytań zmienia wynik.
    """
    rozmowa = Conversation.objects.create(tenant=firma, user_identifier="ocena-generowania")

    with patch("rag.engine.client") as klient:
        klient.embeddings.create.return_value = _wektor_pytania(wzorzec, pytanie)
        wiadomosci, fragmenty, _faqs = build_chat_messages(firma, rozmowa, pytanie.tresc)

    start = time.perf_counter()
    wynik = get_openai_response(wiadomosci, model=model, temperatura=temperatura)
    sekund = time.perf_counter() - start

    obcinacz = ObcinaczZnacznika()
    tresc = obcinacz.podaj(wynik["content"]) + obcinacz.zakoncz()

    return Odpowiedz(
        pytanie=pytanie,
        odmowil=obcinacz.brak_pokrycia,
        tresc=tresc,
        fragmentow=len(fragmenty),
        tokenow=wynik["tokens"],
        sekund=sekund,
    )


def ocen_generowanie(model=None, powtorzen=1, po_pytaniu=None, temperatura=...) -> OcenaGenerowania:
    """
    Cały korpus przez model, `powtorzen` razy.

    `po_pytaniu` dostaje każdą odpowiedź od razu po jej otrzymaniu - przebieg
    na dużym modelu trwa minutę i bez tego wygląda jak zawieszenie.

    `temperatura=None` pomija parametr. Potrzebne do porównywania modeli:
    `gpt-5.6-luna` odrzuca każdą wartość poza domyślną, więc jedynym
    ustawieniem WSPÓLNYM dla niego i dla gpt-4o-mini jest brak parametru.
    Porównanie modelu przy 0,2 z modelem przy domyślnej mierzyłoby dwie
    zmiany naraz i nie dałoby się powiedzieć, która co zrobiła.
    """
    wzorzec = wczytaj_wzorzec()
    firma, _po_id = zaloz_baze_wiedzy(wzorzec)

    odpowiedzi = []
    for _ in range(powtorzen):
        for pytanie in PYTANIA:
            odpowiedz = zapytaj(
                firma,
                pytanie,
                wzorzec,
                model=model or settings.OPENAI_CHAT_MODEL,
                temperatura=temperatura,
            )
            odpowiedzi.append(odpowiedz)
            if po_pytaniu:
                po_pytaniu(odpowiedz)

    return OcenaGenerowania(odpowiedzi=odpowiedzi)


def niestabilne(ocena: OcenaGenerowania) -> list[tuple[Pytanie, int, int]]:
    """
    Pytania, na których powtórzenia dały różne rozstrzygnięcia.

    Temperatura wynosi 0,2, a nie zero, więc model bywa niezdecydowany - i to
    jest wynik sam w sobie. Pytanie, na którym model raz stawia znacznik,
    a raz nie, znaczy, że u prawdziwego odwiedzającego zachowa się losowo.
    Bez tej listy jeden przebieg wygląda na rozstrzygający.
    """
    po_pytaniu: dict[str, list[bool]] = {}
    tresci: dict[str, Pytanie] = {}
    for odpowiedz in ocena.odpowiedzi:
        po_pytaniu.setdefault(odpowiedz.pytanie.tresc, []).append(odpowiedz.odmowil)
        tresci[odpowiedz.pytanie.tresc] = odpowiedz.pytanie

    rozjazdy = []
    for tresc, decyzje in po_pytaniu.items():
        odmow = sum(decyzje)
        if 0 < odmow < len(decyzje):
            rozjazdy.append((tresci[tresc], odmow, len(decyzje)))
    return rozjazdy


def opisz_bledy(ocena: OcenaGenerowania) -> list[str]:
    """Co konkretnie poszło nie tak. Sama liczba mówi, że gorzej, nie mówi czemu."""
    opisy = []
    for odpowiedz in ocena.odpowiedzi:
        pytanie = odpowiedz.pytanie
        if pytanie.ma_odpowiedz and odpowiedz.odmowil:
            if not odpowiedz.fragmentow:
                # Nie wina modelu: nic nie dostal. Osobna linia, zeby nie
                # czytalo sie tego jako bledu generowania.
                opisy.append(f"  ODMOWA, ale bez fragmentow (pudlo wyszukiwania): {pytanie.tresc}")
            else:
                opisy.append(f"  ODMOWA mimo pokrycia: {pytanie.tresc}")
        elif not pytanie.ma_odpowiedz and not odpowiedz.odmowil:
            opisy.append(
                f"  ODPOWIEDZIAL mimo braku pokrycia [{pytanie.grupa}]: {pytanie.tresc}\n"
                f"      -> {odpowiedz.tresc[:110]}"
            )
        elif odpowiedz.trafil_fakt is False:
            oczekiwane = " / ".join(sorted(pytanie.fakty))
            opisy.append(
                f"  BEZ KONKRETU (brak {oczekiwane}): {pytanie.tresc}\n"
                f"      -> {odpowiedz.tresc[:110]}"
            )
    return opisy
