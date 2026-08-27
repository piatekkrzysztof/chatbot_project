"""
Ruch prawdziwy kontra rozmowa testowa właściciela.

Panel pozwala właścicielowi rozmawiać z własnym botem — inaczej po wgraniu
wiedzy nie ma jak sprawdzić, czy bot cokolwiek z niej umie, zanim wystawi go
na żywo. Ale te rozmowy nie są ruchem klientów i nie mogą wchodzić do liczb.

Najbardziej boli to przy lukach w wiedzy: właściciel testuje bota, wpisując
akurat te pytania, o których wie, że są trudne. Gdyby to szło do raportu,
sam wypełniłby sobie listę „czego szukają Twoi klienci" własnymi próbami —
i zepsuł jedyną liczbę w tym produkcie, która mówi coś o rynku, a nie o nas.

Wszystko przez jedno miejsce, bo poprzednim razem dwie definicje tego samego
(pulpit i raport tygodniowy) zdążyły się rozjechać, zanim ktokolwiek zauważył.
"""

from chat.models import ChatMessage, Conversation, PromptLog

# Wartość pola Conversation.source. Kolumna istniała od początku (widget,
# panel, API), więc nie potrzeba migracji ani nowej flagi.
ZRODLO_TESTOWE = "test"


def rozmowy_klientow(tenant):
    """Rozmowy prawdziwych odwiedzających — bez prób właściciela."""
    return Conversation.objects.filter(tenant=tenant).exclude(source=ZRODLO_TESTOWE)


def wiadomosci_klientow(tenant):
    return ChatMessage.objects.filter(conversation__tenant=tenant).exclude(
        conversation__source=ZRODLO_TESTOWE
    )


def logi_klientow(tenant):
    """
    Wpisy PromptLog z ruchu prawdziwego.

    `conversation` bywa puste (SET_NULL po skasowaniu rozmowy w ramach
    retencji), a takie wpisy MAJĄ zostać — pochodzą sprzed usunięcia rozmowy,
    nie z testu. Zachowanie `exclude()` przy pustym powiązaniu jest tu
    kluczowe i dlatego ma własny test.
    """
    return PromptLog.objects.filter(tenant=tenant).exclude(conversation__source=ZRODLO_TESTOWE)
