"""
Testy PRZYRZĄDU do oceny generowania, nie samego modelu.

Model jest tu podstawiony celowo. Prawdziwy kosztuje pieniądze i odpowiada za
każdym razem inaczej, więc test, który by go wołał, byłby albo drogi, albo
losowy, albo jedno i drugie. Zachowanie prawdziwego modelu mierzy komenda
`ocen_generowanie`, uruchamiana świadomie.

To, co tu sprawdzamy, to czy przyrząd liczy to, co obiecuje - bo miara, która
myli się o połowę, jest gorsza od jej braku. Przy takiej pomyłce podjęłoby się
decyzję o zmianie modelu na liczbach wyglądających jak dowód.
"""

from unittest.mock import patch

import pytest

from accounts.models import Tenant
from api.utils.chat_engine import ZNACZNIK_BRAKU
from chat.models import Conversation
from documents.models import Document
from rag.ocena.generowanie import OcenaGenerowania, niestabilne, ocen_generowanie
from rag.ocena.korpus import PYTANIA

pytestmark = pytest.mark.django_db


def udawany_model(tresc, tokenow=100):
    """Model, który zawsze odpowiada tym samym."""
    return {"content": tresc, "tokens": tokenow}


def uruchom(odpowiedzi, powtorzen=1):
    """`odpowiedzi` to funkcja (messages, model, ...) -> slownik jak z API."""
    with patch("rag.ocena.generowanie.get_openai_response", side_effect=odpowiedzi) as wolanie:
        ocena = ocen_generowanie(model="model-testowy", powtorzen=powtorzen)
    return ocena, wolanie


class TestLiczenia:
    def test_model_ktory_zawsze_odmawia(self):
        ocena, _ = uruchom(lambda *a, **k: udawany_model(f"{ZNACZNIK_BRAKU} Nie wiem."))

        # Wszystkie pytania spoza bazy trafione, ale za cene odmowy na kazdym
        # pytaniu pokrytym. Bez drugiej liczby taki model wyglada na doskonaly.
        assert ocena.odmowy_trafne == 1.0
        assert ocena.odmowy_falszywe == 1.0

    def test_model_ktory_nigdy_nie_odmawia(self):
        ocena, _ = uruchom(lambda *a, **k: udawany_model("Oczywiscie, sluze pomoca."))

        assert ocena.odmowy_trafne == 0.0
        assert ocena.odmowy_falszywe == 0.0

    def test_znacznik_w_srodku_zdania_nie_liczy_sie_jako_odmowa(self):
        """
        Protokół mówi: znacznik na SAMYM POCZĄTKU. Gdyby liczyło się samo jego
        wystąpienie, model cytujący instrukcję w treści („nie wpisuję wtedy
        [BRAK_ODPOWIEDZI]") byłby liczony jako odmawiający - a widget i tak
        pokazałby tę odpowiedź odwiedzającemu.
        """
        ocena, _ = uruchom(lambda *a, **k: udawany_model(f"Cena to 120 zl {ZNACZNIK_BRAKU}"))

        assert ocena.odmowy_trafne == 0.0
        assert ocena.odmowy_falszywe == 0.0

    def test_konkret_z_fragmentu_jest_rozpoznawany(self):
        ocena, _ = uruchom(lambda *a, **k: udawany_model("Kosztuje 120 zl, 80 zl, 18, 20, 24, 48."))

        # Nie 100%: ta odpowiedz nie zawiera "3-5" ani slowa o sobotach.
        assert 0.0 < ocena.oparte_na_wiedzy < 1.0

    def test_odpowiedz_bez_konkretu_nie_liczy_sie_jako_oparta_na_wiedzy(self):
        ocena, _ = uruchom(lambda *a, **k: udawany_model("Zapraszamy do kontaktu w tej sprawie."))

        assert ocena.oparte_na_wiedzy == 0.0

    def test_pytanie_bez_sprawdzalnego_faktu_nie_wchodzi_do_mianownika(self):
        """
        „Czy dostanę rower zastępczy" ma odpowiedź przeczącą - nie ma w niej
        liczby, która odróżniałaby ją od uprzejmej odmowy. Zaliczenie go
        w ciemno zawyżałoby wynik, a wliczenie jako porażki - zaniżało.
        """
        ocena, _ = uruchom(lambda *a, **k: udawany_model("Nie."))

        z_odpowiedzia = [p for p in PYTANIA if p.ma_odpowiedz]
        assert ocena.sprawdzalnych_faktow == len(z_odpowiedzia) - 1

    def test_odmowa_nie_jest_oceniana_pod_katem_konkretu(self):
        # Odmowa nie ma prawa zawierac ceny. Liczenie jej jako "bez konkretu"
        # karaloby model dwa razy za to samo rozstrzygniecie.
        ocena, _ = uruchom(
            lambda *a, **k: udawany_model(f"{ZNACZNIK_BRAKU} Nie mam tej informacji.")
        )

        assert ocena.sprawdzalnych_faktow == 0


class TestUczciwosciPomiaru:
    def test_kazde_pytanie_dostaje_swieza_rozmowe(self):
        """
        Każde pytanie w osobnej rozmowie, żeby historia nie zmieniała wyniku.

        Pierwsza wersja tego testu sprawdzała tylko, czy w promptach nie ma ról
        „assistant" - i przechodziła także wtedy, gdy WSZYSTKIE pytania szły
        w jednej rozmowie. Bo przyrząd nie zapisuje odpowiedzi do bazy, więc
        historia jest pusta niezależnie od tego, ile rozmów założono. Test
        dawał zapewnienie, którego nie miał czym poprzeć - wyszło to dopiero
        przy weryfikacji mutacyjnej.

        Sprawdzamy teraz sam mechanizm: liczbę założonych rozmów. Zapewnienie
        zostanie prawdziwe także wtedy, gdy przyrząd kiedyś zacznie zapisywać
        wymianę do bazy.
        """
        rozmow_przed = Conversation.objects.count()

        _, wolanie = uruchom(lambda *a, **k: udawany_model("Odpowiedz."), powtorzen=2)

        assert Conversation.objects.count() - rozmow_przed == len(PYTANIA) * 2

        for zapis in wolanie.call_args_list:
            role = [w["role"] for w in zapis.args[0]]
            assert "assistant" not in role, "Historia poprzednich pytan wyciekla do promptu."
            assert role.count("user") == 1

    def test_pyta_kazde_pytanie_tyle_razy_ile_powtorzen(self):
        ocena, wolanie = uruchom(lambda *a, **k: udawany_model("Odpowiedz."), powtorzen=3)

        assert wolanie.call_count == len(PYTANIA) * 3
        assert len(ocena.odpowiedzi) == len(PYTANIA) * 3

    def test_uzywa_wskazanego_modelu(self):
        # Bez tego porownanie dwoch modeli mierzyloby dwa razy ten sam.
        _, wolanie = uruchom(lambda *a, **k: udawany_model("Odpowiedz."))

        assert all(zapis.kwargs["model"] == "model-testowy" for zapis in wolanie.call_args_list)

    def test_nie_wola_prawdziwego_api_embeddingow(self):
        """
        Wektor pytania pochodzi z zamrożonego wzorca. Gdyby szedł do API,
        pomiar generowania płaciłby też za embeddingi, a wyszukiwanie
        przestałoby być deterministyczne między przebiegami.
        """
        with patch("rag.engine.client") as klient:
            uruchom(lambda *a, **k: udawany_model("Odpowiedz."))

        assert klient.embeddings.create.call_count == 0

    def test_model_dostaje_fragmenty_z_bazy_wiedzy(self):
        """
        Najważniejszy test w tym pliku.

        Gdyby wyszukiwanie zwracało pustkę, model odmawiałby na każde pytanie
        słusznie - bo nic nie dostał - a pomiar pokazałby „odmowy trafne 100%"
        i wyglądałoby to na doskonały model. Mierzyłby wtedy zepsute
        wyszukiwanie pod nazwą jakości generowania.

        Liczba pytań bez fragmentów musi się zgadzać z tym, co niezależnie
        mierzy ocena wyszukiwania. Nie „ma być zero": przy obecnym progu jedno
        pytanie („czy pracujecie w weekend") faktycznie nic nie znajduje i to
        jest ta sama luka, którą tamta ocena pokazuje jako trafność 90,9%.
        Wpisanie tu jedynki na sztywno rozjechałoby się z nią po cichu przy
        pierwszej zmianie progu.
        """
        from rag.ocena.przebieg import ocen_na_wzorcu

        _ocena_wyszukiwania, wyniki = ocen_na_wzorcu()
        pudla_wyszukiwania = sum(1 for w in wyniki if w.pytanie.ma_odpowiedz and not w.znalezione)

        ocena, wolanie = uruchom(lambda *a, **k: udawany_model("Odpowiedz."))

        assert len(ocena.bez_fragmentow) == pudla_wyszukiwania, (
            "Model dostaje inny zestaw fragmentow niz ten, ktory mierzy ocena "
            f"wyszukiwania. Bez fragmentow: "
            f"{[o.pytanie.tresc for o in ocena.bez_fragmentow]}"
        )

        systemowe = [zapis.args[0][0]["content"] for zapis in wolanie.call_args_list]
        assert any("Przeglad podstawowy roweru kosztuje 120 zl" in tresc for tresc in systemowe)

    def test_nie_zostawia_smieci_w_bazie(self):
        przed_firm = Tenant.objects.count()
        przed_dokumentow = Document.objects.count()

        with patch("rag.ocena.generowanie.get_openai_response") as model:
            model.return_value = udawany_model("Odpowiedz.")
            from django.db import transaction

            with transaction.atomic():
                ocen_generowanie(model="model-testowy", powtorzen=1)
                transaction.set_rollback(True)

        assert Tenant.objects.count() == przed_firm
        assert Document.objects.count() == przed_dokumentow


class TestNiestabilnosci:
    def test_rozjazd_miedzy_powtorzeniami_jest_zglaszany(self):
        """
        Temperatura to 0,2, nie zero. Pytanie, na którym model raz stawia
        znacznik, a raz nie, znaczy, że u prawdziwego odwiedzającego zachowa
        się losowo - i to jest wynik sam w sobie, nie szum do uśrednienia.
        """
        licznik = {"n": 0}

        def raz_tak_raz_nie(*args, **kwargs):
            licznik["n"] += 1
            tresc = f"{ZNACZNIK_BRAKU} Nie wiem." if licznik["n"] % 2 else "Kosztuje 120 zl."
            return udawany_model(tresc)

        ocena, _ = uruchom(raz_tak_raz_nie, powtorzen=2)

        assert len(niestabilne(ocena)) == len(PYTANIA)

    def test_zgodne_powtorzenia_nie_sa_zglaszane(self):
        # Ostrzezenie, ktore pojawia sie zawsze, przestaje cokolwiek znaczyc.
        ocena, _ = uruchom(lambda *a, **k: udawany_model("Kosztuje 120 zl."), powtorzen=3)

        assert niestabilne(ocena) == []


class TestPustejOceny:
    def test_pusta_ocena_nie_dzieli_przez_zero(self):
        # Przebieg przerwany po zerowej liczbie pytan nie ma prawa wywalic
        # sie na wypisywaniu wyniku - komunikat o bledzie zginalby wtedy pod
        # ZeroDivisionError z formatowania.
        pusta = OcenaGenerowania()

        assert pusta.odmowy_trafne == 0.0
        assert pusta.odmowy_falszywe == 0.0
        assert pusta.oparte_na_wiedzy == 0.0
        assert pusta.sekund_srednio == 0.0


class TestPudelWyszukiwania:
    """
    Pytania, na które wyszukiwarka nic nie podała, nie są winą modelu.

    Obie rzeczy tutaj to poprawki po PIERWSZYM prawdziwym uruchomieniu
    komendy - czyli po tym, jak przyrząd zbudowany do wyłapywania kłamiących
    liczb sam podał dwie.
    """

    def test_liczy_rozne_pytania_a_nie_odpowiedzi(self):
        """
        Przy trzech powtórzeniach jedno pudło wyszukiwania daje trzy wpisy.
        Komenda pisała wtedy „3 pytania bez fragmentów" przy jednym prawdziwym
        pudle - liczba wyglądała na trzy razy gorszą, niż była.
        """
        ocena, _ = uruchom(lambda *a, **k: udawany_model("Odpowiedz."), powtorzen=3)

        assert len(ocena.bez_fragmentow) == 3 * len(ocena.pytania_bez_fragmentow)
        assert len(ocena.pytania_bez_fragmentow) == len(set(ocena.pytania_bez_fragmentow))

    def test_odmowa_bez_fragmentow_nie_liczy_sie_jako_falszywa(self):
        """
        Model, który odmawia nie dostawszy ani jednego fragmentu, zachowuje się
        poprawnie. Wliczanie tego do jego wyniku mieszałoby jakość modelu
        z ustawieniem progu - i wynik zmieniałby się przy zmianie progu, mimo
        że model zostałby ten sam.

        Podstawiony model odmawia dokładnie wtedy, gdy nie dostał fragmentów -
        czyli zachowuje się poprawnie na całym korpusie. Przy prawidłowym
        liczeniu jego odsetek fałszywych odmów wynosi zero. Wersja licząca
        także pudła wyszukiwania obarczyłaby go winą za próg.
        """

        def odmawia_gdy_nic_nie_dostal(wiadomosci, *args, **kwargs):
            systemowa = wiadomosci[0]["content"]
            if "Fragmenty dokumentów firmy" in systemowa:
                return udawany_model("Kosztuje 120 zl.")
            return udawany_model(f"{ZNACZNIK_BRAKU} Nie mam tej informacji.")

        ocena, _ = uruchom(odmawia_gdy_nic_nie_dostal)

        assert ocena.pytania_bez_fragmentow, "Test zaklada istnienie pudla wyszukiwania."
        assert ocena.odmowy_falszywe == 0.0, (
            f"Pudlo wyszukiwania weszlo do liczby opisujacej model: {ocena.pytania_bez_fragmentow}"
        )
