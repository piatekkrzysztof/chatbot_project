"""
Ocena jakości wyszukiwania fragmentów.

Kategoria ryzyka: RDZEŃ PRODUKTU. Cała obietnica brzmi „bot odpowiada z Twojej
bazy wiedzy". Do tej pory nie było jak sprawdzić, czy ją spełnia - ani czy
zmiana w cięciu dokumentów, w progu odległości albo w modelu embeddingów jej
nie psuje. Każda taka zmiana szła na wyczucie.

Ten plik nie sprawdza, czy kod się wykonuje. Sprawdza, czy DZIAŁA DOBRZE -
i psuje się wtedy, gdy zaczyna działać gorzej niż dziś.

Skąd biorą się liczby
---------------------
Progi poniżej pochodzą z POMIARU wykonanego 4 września 2026 na zamrożonym
wzorcu, nie z życzenia. Zapas jest wąski, bo to jest test regresji: ma się
zaczerwienić, kiedy zrobi się gorzej, a nie czekać, aż zrobi się bardzo źle.

Wektory są prawdziwe - policzone raz modelem text-embedding-3-small i zapisane
w rag/ocena/wzorzec.json. CI liczy więc realne odległości bez ani jednego
wywołania płatnego API. Udawany model embeddingów dałby „trafność 100%",
która nie mówiłaby nic poza tym, że atrapa zgadza się sama ze sobą.
"""

import pytest

from rag.ocena.miary import opisz_bledy
from rag.ocena.przebieg import ocen_na_wzorcu

#: Zmierzone 04.09.2026 przy RAG_MAX_DISTANCE = 1.15:
#:   trafnosc 100.0%, na 1. miejscu 81.8%, MRR 0.909, cisza 37.5%
#:
#: Podlogi z waskim zapasem: jedno pytanie moze sie zsunac, dwa juz nie.
PROG_TRAFNOSCI = 0.90
PROG_NA_PIERWSZYM = 0.72
PROG_MRR = 0.85

#: Cisza NIE MA zapasu w dol, bo juz jest slaba. Kazde dalsze poluzowanie
#: jest regresja i ma zatrzymac scalenie.
PROG_CISZY = 0.375


@pytest.mark.django_db
class TestJakosciWyszukiwania:
    def test_znajduje_odpowiedzi_ktore_sa_w_bazie(self):
        ocena, wyniki = ocen_na_wzorcu()

        assert ocena.trafnosc >= PROG_TRAFNOSCI, "\n".join(
            ["Wyszukiwanie przestalo znajdowac odpowiedzi:", *opisz_bledy(wyniki)]
        )

    def test_wlasciwy_fragment_lezy_wysoko_w_wynikach(self):
        """
        Sama obecnosc w wynikach nie wystarcza.

        Do modelu trafia ograniczona liczba fragmentow, a dalsze gina w szumie
        blizszych. Fragment znaleziony na piatym miejscu jest wyraznie gorszy
        niz ten sam na pierwszym, a roznicy nie widac w samej trafnosci.
        """
        ocena, wyniki = ocen_na_wzorcu()

        assert ocena.trafnosc_na_pierwszym >= PROG_NA_PIERWSZYM
        assert ocena.srednia_odwrotna_pozycja >= PROG_MRR

    def test_milczy_na_pytania_spoza_bazy_wiedzy(self):
        """
        Najważniejszy test w tym pliku.

        Wyszukiwarka, ktora na kazde pytanie oddaje piec najblizszych
        fragmentow, ma trafnosc bliska stu procent i jest bezuzyteczna: na
        pytanie o zakwas na zurek podaje termin wysylki. Bot, ktory pewnym
        glosem cytuje niezwiazany fragment, jest gorszy od takiego, ktory mowi
        "nie wiem" - klient nie ma jak rozpoznac, ze dostal wymyslona odpowiedz.

        Ten prog jest ustawiony na zmierzonej wartosci BEZ zapasu, bo cisza
        jest dzis slaba (37,5%) i kazde dalsze poluzowanie musi zatrzymac
        scalenie.
        """
        ocena, wyniki = ocen_na_wzorcu()

        assert ocena.cisza >= PROG_CISZY, "\n".join(
            ["Wyszukiwanie przepuszcza wiecej smiecia niz dotad:", *opisz_bledy(wyniki)]
        )

    def test_obie_miary_licza_sie_naraz(self):
        """
        Zabezpieczenie przed poprawianiem jednej liczby kosztem drugiej.

        Prog odleglosci przesuwa trafnosc i cisze w przeciwne strony. Gdyby
        test pilnowal tylko jednej z nich, dalby sie "naprawic" ustawieniem
        progu w skrajna pozycje - i wyglądaloby to na poprawe.
        """
        ocena, _ = ocen_na_wzorcu()

        assert ocena.liczba_z_odpowiedzia > 0
        assert ocena.liczba_bez_odpowiedzi > 0
        assert ocena.trafnosc >= PROG_TRAFNOSCI
        assert ocena.cisza >= PROG_CISZY


@pytest.mark.django_db
class TestWymianyMiedzyMiarami:
    """
    Wykonalny zapis pomiaru, nie tylko zdanie w opisie zmiany.

    Przemiatanie progu 04.09.2026 dalo:

        prog | trafnosc | na 1. | MRR   | cisza
        -----+----------+-------+-------+------
        0.90 |   81.8%  | 72.7% | 0.773 | 87.5%
        0.95 |   90.9%  | 72.7% | 0.818 | 75.0%
        1.05 |  100.0%  | 81.8% | 0.909 | 62.5%
        1.15 |  100.0%  | 81.8% | 0.909 | 37.5%   <- ustawienie obecne
        1.20 |  100.0%  | 81.8% | 0.909 | 25.0%

    Wniosek: obecny prog oddaje 25 punktow ciszy za nic. Zmiana na 1.05 daje
    pelna trafnosc i wyraznie lepsza powsciagliwosc.

    NIE zmieniam go tutaj. Korpus ma dziesiec fragmentow, a odleglosci zaleza
    od konkretnych dokumentow klienta - od tego jest `zmierz_prog_rag`, ktore
    liczy rozklad na zywych danych. Decyzja o progu produkcyjnym wymaga
    sprawdzenia na prawdziwej bazie wiedzy, nie na tym korpusie.
    """

    def test_ciasniejszy_prog_poprawia_cisze_nie_psujac_trafnosci(self):
        luzny, _ = ocen_na_wzorcu(max_distance=1.15)
        ciasny, _ = ocen_na_wzorcu(max_distance=1.05)

        assert ciasny.trafnosc == luzny.trafnosc
        assert ciasny.cisza > luzny.cisza

    def test_zbyt_ciasny_prog_zaczyna_gubic_odpowiedzi(self):
        # Druga strona wymiany. Bez tego ktos moglby "poprawic" cisze do stu
        # procent, zabierajac botowi wiedze.
        bardzo_ciasny, _ = ocen_na_wzorcu(max_distance=0.90)

        assert bardzo_ciasny.cisza > 0.80
        assert bardzo_ciasny.trafnosc < 0.90
