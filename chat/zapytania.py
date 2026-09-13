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

To samo dotyczy historii wgranej z pliku CSV (F19). Import zapisywał wpisy
jak ruch z widgetu, więc wgranie starych rozmów zawyżało pulpit i eksport.
"""

from django.db.models import Q

from chat.models import ChatMessage, Conversation, PromptLog

# Wartość pola Conversation.source. Kolumna istniała od początku (widget,
# panel, API), więc nie potrzeba migracji ani nowej flagi.
ZRODLO_TESTOWE = "test"

# Znacznik historii wgranej z CSV. Import zapisywał go od początku w
# PromptLog.source i Conversation.user_identifier; od F19 także w
# Conversation.source. PromptLog.source ma listę wyborów, na której tej
# wartości nie ma - świadomie bez migracji samych wyborów, bo pełne
# odtworzenie kopii wymaga zgodnego stanu migracji.
ZRODLO_IMPORTU = "imported"


def rozmowy_klientow(tenant):
    """Rozmowy prawdziwych odwiedzających — bez prób właściciela i importu."""
    return (
        Conversation.objects.filter(tenant=tenant)
        .exclude(source=ZRODLO_TESTOWE)
        .exclude(Q(source=ZRODLO_IMPORTU) | Q(user_identifier=ZRODLO_IMPORTU))
    )


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
    return (
        PromptLog.objects.filter(tenant=tenant)
        .exclude(conversation__source=ZRODLO_TESTOWE)
        .exclude(source=ZRODLO_IMPORTU)
    )
