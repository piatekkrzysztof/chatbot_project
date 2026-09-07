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

#: Przemiatanie progu po przejsciu na 512 wymiarow.
#: `manage.py ocen_rag --przemiataj`, 7 wrzesnia 2026:
#:
#:     prog | trafnosc | na 1. | MRR   | cisza
#:     -----+----------+-------+-------+------
#:     0.80 |    54.5% | 54.5% | 0.545 | 100.0%
#:     0.85 |    63.6% | 54.5% | 0.576 | 100.0%
#:     0.90 |    90.9% | 72.7% | 0.803 |  75.0%
#:     0.96 |    90.9% | 72.7% | 0.803 |  75.0%   <- ustawienie obecne
#:     0.98 |    90.9% | 72.7% | 0.803 |  75.0%
#:     0.99 |    90.9% | 72.7% | 0.803 |  62.5%
#:     1.05 |   100.0% | 81.8% | 0.894 |  50.0%
#:     1.15 |   100.0% | 81.8% | 0.894 |  25.0%   <- domyslna sprzed migracji
#:
#: Caly odcinek 0.90-0.98 jest tu PLASKI - te same liczby przy kazdym progu.
#: Zestaw pomiarowy nie rozstrzyga wiec, gdzie w tym oknie postawic prog,
#: i nie nalezy go o to pytac. Rozstrzygnela to historia pytan z produkcji:
#: przy 0.98 przechodzilo pytanie, na ktore firma nie odpowiada. Pelny wywod
#: przy RAG_MAX_DISTANCE w settings/base.py.
#:
#: DLACZEGO TO JEST TU NAPISANE: pierwsza wersja tej zmiany ustawiala prog na
#: 0.90, bo tak wychodzilo z porownania samego zestawu pomiarowego. Na
#: prawdziwej bazie wiedzy 0.90 odcinalo pytanie "w jakich godzinach
#: jestescie otwarci", ktore lezy na 0.952 - i lezalo na 0.953 takze przed
#: migracja. Dziesiec fragmentow wymyslonego sklepu wystarczy, zeby wykryc
#: regresje, i nie wystarczy, zeby ustawic prog.
#:
#: Czego tu juz NIE MA: rozjazdu miedzy kodem a serwerem. Wczesniej base.py
#: mial 1.15, a Render zmienna srodowiskowa 1.0, wiec te podlogi opisywaly
#: prog, ktorego produkt nigdy nie uzywal. Teraz domyslna wartosc w kodzie
#: jest wartoscia produkcyjna i CI mierzy to, co robi bot.
#:
#: Do progu produkcyjnego sluzy zmierz_prog_rag, liczone na zywej bazie wiedzy.

#: Zmierzone 07.09.2026 przy RAG_MAX_DISTANCE = 0.96:
#:   trafnosc 90.9%, na 1. miejscu 72.7%, MRR 0.803, cisza 75.0%
#:
#: Podlogi z zapasem na jedno pytanie. Pytan z odpowiedzia jest 11, wiec
#: jedno zsuniete to 9.1 punktu procentowego - dwa maja zatrzymac scalenie.
PROG_TRAFNOSCI = 0.81
PROG_NA_PIERWSZYM = 0.63
PROG_MRR = 0.75

#: Cisza NIE MA zapasu w dol.
#:
#: Przed migracja powodem bylo to, ze cisza jest slaba (37.5%). Teraz jest
#: dobra (75.0%), a powod jest inny i mocniejszy: bot, ktory pewnym glosem
#: cytuje niezwiazany fragment, jest gorszy od takiego, ktory mowi "nie wiem",
#: bo klient nie ma jak odroznic jednego od drugiego. Kazde poluzowanie tej
#: liczby ma zatrzymac scalenie i wymagac decyzji, nie poprawki progu.
PROG_CISZY = 0.75


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

    Liczby sa w komentarzu przy progach na gorze pliku. Tutaj sa te same
    liczby zapisane wykonalnie: opis w komentarzu zdezaktualizuje sie po cichu,
    asercja zaczerwieni sie od razu.

    Dlaczego te progi, a nie inne
    -----------------------------
    Po zmianie wymiaru wektora skala odleglosci przesunela sie w dol, wiec
    para, ktora pokazywala wymiane przy 1536 wymiarach (0.90 kontra 1.15),
    lezy teraz po jednej stronie: 0.90 jest ustawieniem produkcyjnym, a nie
    "za ciasnym". Za ciasny zaczyna sie ponizej 0.85.
    """

    def test_ciasniejszy_prog_poprawia_cisze_nie_psujac_trafnosci(self):
        luzny, _ = ocen_na_wzorcu(max_distance=1.15)
        ciasny, _ = ocen_na_wzorcu(max_distance=1.05)

        assert ciasny.trafnosc == luzny.trafnosc
        assert ciasny.cisza > luzny.cisza

    def test_zbyt_ciasny_prog_zaczyna_gubic_odpowiedzi(self):
        # Druga strona wymiany. Bez tego ktos moglby "poprawic" cisze do stu
        # procent, zabierajac botowi wiedze.
        bardzo_ciasny, _ = ocen_na_wzorcu(max_distance=0.80)

        assert bardzo_ciasny.cisza > 0.90
        assert bardzo_ciasny.trafnosc < 0.60
