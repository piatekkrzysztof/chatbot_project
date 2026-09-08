"""
Wiadomość systemowa: kim jest bot, co wie o firmie i jak ma się zachowywać.

Każde zdanie w tym prompcie kosztuje tokeny przy KAŻDYM pytaniu każdego
klienta, a kilka z nich zostało dopisanych dopiero po tym, jak brak takiego
zdania zobaczono w produkcji. Dlatego przy każdym stoi komentarz mówiący, co
się działo bez niego - inaczej pierwsza osoba porządkująca ten prompt skróci
go do trzech zdań i przywróci wszystkie te awarie naraz.

Zmiany w tym pliku mierzy `manage.py ocen_generowanie`: 19 pytań, trzy liczby,
kilkanaście groszy za przebieg. Nie ma powodu zgadywać.

Wydzielone z chat_engine.py 8 września 2026.
"""

from accounts.models import WIDGET_LANGUAGE_ADVERBS
from api.utils.language import jezyk_odpowiedzi
from api.utils.pokrycie import ZNACZNIK_BRAKU


def has_company_knowledge(tenant, chunks, faqs):
    """
    Czy do tej odpowiedzi bot ma jakąkolwiek wiedzę o firmie.

    Liczy się wszystko, co realnie trafia do promptu — opis firmy, regulamin,
    dopasowane fragmenty dokumentów i wpisy FAQ. Pusto oznacza, że model
    odpowiadałby wyłącznie z własnych domysłów.
    """
    return bool(tenant.gpt_prompt or tenant.regulamin or chunks or faqs)


def language_instruction(tenant, message=None):
    """
    W jakim języku bot ma odpowiadać.

    Prompt miał wcześniej zaszyte "odpowiadaj po polsku", więc anglojęzyczny
    odwiedzający dostawał polską odpowiedź na angielskie pytanie.

    Instrukcja wskazuje zawsze JEDEN język, nigdy listy dozwolonych. Wersje
    opisujące listę wypadały na modelu niestabilnie: albo lustrzanie dopasowywał
    język pytania i ignorował listę klienta, albo zwijał wszystko do domyślnego
    i ignorował zezwolenie. Wybór należy więc do kodu (api.utils.language),
    a model dostaje gotową decyzję.
    """
    domyslny = tenant.default_language()
    if tenant.uses_fixed_language() or not message:
        kod = domyslny
    else:
        kod = jezyk_odpowiedzi(message, tenant.languages(), domyslny)
    forma = WIDGET_LANGUAGE_ADVERBS[kod]
    return f"Odpowiadaj wyłącznie {forma}, niezależnie od języka pytania."


def build_system_prompt(tenant, chunks, faqs, message=None):
    """
    Buduje wiadomość systemową: kim jest bot, co wie o firmie i jak ma się zachowywać.
    Wiedza (dokumenty + FAQ) trafia tutaj, żeby historia rozmowy pozostała czysta.

    `message` to bieżące pytanie odwiedzającego — potrzebne wyłącznie do
    ustalenia języka odpowiedzi. Bez niego prompt wychodzi w języku domyślnym.
    """
    parts = [
        f"Jesteś asystentem firmy {tenant.name}. Odpowiadasz klientom na stronie internetowej.",
        "Odpowiadaj zwięźle i konkretnie, w uprzejmym tonie.",
        language_instruction(tenant, message),
        # Sama instrukcja "nie zmyślaj" nie wystarcza: model odmawia przy pytaniach
        # o ceny czy godziny, ale na "czym zajmuje się wasza firma?" wnioskuje profil
        # działalności z samej nazwy i podaje go jako fakt. Dlatego ta klasa pytań
        # jest tu wymieniona wprost.
        "Opieraj się wyłącznie na wiedzy podanej niżej. Jeśli odpowiedź nie wynika "
        "z niej wprost, powiedz że nie masz tej informacji i zaproponuj kontakt z firmą.",
        # Sama instrukcja "opieraj sie na podanej wiedzy" nie obejmuje pytan,
        # ktore z firma nie maja nic wspolnego - model traktuje je jako zwykla
        # rozmowe i odpowiada z wlasnej wiedzy o swiecie. Na stronie sklepu
        # rowerowego wygladalo to tak: "Stolica Australii jest Canberra"
        # i "pierwiastek z 256 wynosi okolo 16,06" (blednie).
        #
        # Znacznik jest tu powtorzony WPROST i to nie jest nadmiarowe. Wersja
        # bez niego ("traktuj jak pytania bez pokrycia") kazala modelowi
        # przestac odpowiadac, ale nie kazala postawic znacznika - wiec pisal
        # "niestety nie moge odpowiedziec na to pytanie" bez niego. Zachowanie
        # wobec odwiedzajacego poprawne, protokol zlamany: zadne zapytanie nie
        # powstawalo. Zmierzone: odmowy trafne 70,8% -> 37,5%, czyli GORZEJ
        # niz przed zmiana.
        f"Pytania niezwiązane z tą firmą — o świat, historię, matematykę, pogodę, "
        f"definicje — też są pytaniami, na które nie masz wiedzy firmy. NIE odpowiadaj "
        f"na nie z własnej wiedzy, nawet jeśli znasz odpowiedź i jest prosta; zacznij "
        f"odpowiedź od {ZNACZNIK_BRAKU} dokładnie tak samo jak przy każdym innym braku.",
        # Wyjatek, bez ktorego zdanie wyzej psuje pierwsze zdanie rozmowy:
        # wersja bez niego odrzucala "Czesc, jak sie masz?" zimnym "nie udzielam
        # informacji na ten temat" - i zakladala wlascicielowi zapytanie
        # o powitanie.
        "Powitania, podziękowania, pożegnania i zwykłą uprzejmość odbieraj normalnie "
        "i odpowiadaj na nie ciepło, bez tego znacznika. To nie są pytania o wiedzę.",
        "Nigdy nie zgaduj na podstawie nazwy firmy ani ogólnej wiedzy o branży. "
        "Dotyczy to zwłaszcza pytań o to, czym firma się zajmuje, co oferuje, "
        "jakie ma ceny, godziny otwarcia i zasady — o tym wypowiadasz się tylko wtedy, "
        "gdy wynika to z wiedzy podanej niżej.",
        # Bez tego nie mamy jak odróżnić odpowiedzi od odmowy. Retrieval tego nie
        # powie: zwraca najbliższe fragmenty niezależnie od tego, czy odpowiadają
        # na pytanie. Wie o tym tylko model — więc niech powie wprost.
        f"Gdy nie potrafisz odpowiedzieć na podstawie wiedzy podanej niżej, "
        f"ZACZNIJ odpowiedź dokładnie od {ZNACZNIK_BRAKU}, a dalej pisz normalnie "
        f"(odmowa i propozycja kontaktu z firmą, w języku rozmowy). Znacznik "
        f"wpisz tylko na samym początku i nigdy w środku zdania. Gdy odpowiadasz "
        f"na podstawie podanej wiedzy — nie wpisuj go wcale.",
    ]

    if not has_company_knowledge(tenant, chunks, faqs):
        # Bez tego bloku model dostaje pusty prompt z samą nazwą firmy i wypełnia
        # lukę własnymi domysłami — na stronie klienta wygląda to jak wymyślona oferta.
        parts.append(
            "\nUWAGA: nie masz żadnych informacji o tej firmie. Na każde pytanie "
            "dotyczące jej działalności, oferty lub zasad odpowiedz wprost, że nie "
            "posiadasz tych informacji, i poproś o kontakt z firmą. Możesz jedynie "
            "uprzejmie się przywitać i podtrzymać rozmowę. Samą odmowę napisz "
            "w języku wskazanym wyżej, nie zawsze po polsku."
        )

    if tenant.gpt_prompt:
        parts.append(f"\nO firmie:\n{tenant.gpt_prompt.strip()}")

    if faqs:
        faq_text = "\n\n".join(f"P: {f.question}\nO: {f.answer}" for f in faqs)
        parts.append(f"\nNajczęstsze pytania i odpowiedzi:\n{faq_text}")

    if chunks:
        docs_text = "\n\n---\n\n".join(
            f"[Źródło: {chunk.document.name}]\n{chunk.content}" for chunk in chunks
        )
        parts.append(f"\nFragmenty dokumentów firmy:\n{docs_text}")

    if tenant.regulamin:
        parts.append(f"\nRegulamin:\n{tenant.regulamin.strip()}")

    return "\n".join(parts)
