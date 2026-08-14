"""
Czy zadania w tle naprawdę się wykonują.

Ta usterka jest niewidoczna z założenia. `enqueue()` przy braku brokera albo
workera wykonuje zadanie synchronicznie, żeby wgranie dokumentu nie kończyło
się błędem — i to jest słuszne. Skutek uboczny: nikt się nie dowie, że worker
nie chodzi, bo funkcje sterowane przez użytkownika działają dalej.

Cicho przestają natomiast działać zadania cykliczne, bo tych nikt nie zleca
z żądania HTTP:

  • ponowne pobieranie stron WWW co 12 godzin — płatna obietnica planów Grow
    i Pro (baza wiedzy nadąża za zmianami na stronie klienta),
  • czyszczenie rozmów po okresie retencji — obowiązek wynikający z RODO.

Dlatego nie pytamy tylko brokera „czy ktoś odpowiada", ale też danych: czy
strony faktycznie były ostatnio pobrane i czy w bazie nie zalegają rozmowy
starsze, niż pozwala polityka klienta. Odpowiedź brokera mówi o stanie na
teraz, ślady w danych mówią o tym, co działo się przez ostatnie dni — i to
one są mocniejszym dowodem.
"""
from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Tenant
from api.permissions import IsOwnerOrEmployee
from chat.models import Conversation
from documents.models import WebsiteSource

# Harmonogram przewiduje pobieranie co 12 h. Dajemy podwójny zapas, żeby
# jedno opóźnione uruchomienie nie wyglądało jak awaria.
PROG_POBIERANIA_H = 26


def _stan_brokera():
    """
    Pyta brokera, czy odpowiadają jacyś workerzy.

    Świadomie bez ponawiania połączenia: przy nieosiągalnym Redisie domyślne
    zachowanie Celery to kilka prób z narastającym odstępem, co zamieniłoby
    diagnostykę w żądanie wiszące kilkadziesiąt sekund.
    """
    try:
        from chatbot_project.celery import app

        with app.connection() as polaczenie:
            polaczenie.ensure_connection(max_retries=0, timeout=2)

        odpowiedzi = app.control.ping(timeout=1.5) or []
        nazwy = [nazwa for wpis in odpowiedzi for nazwa in wpis]
        return {
            "broker_osiagalny": True,
            "odpowiedzialo_workerow": len(nazwy),
            "nazwy": nazwy,
        }
    except Exception as blad:
        return {
            "broker_osiagalny": False,
            "odpowiedzialo_workerow": 0,
            "nazwy": [],
            "blad": f"{type(blad).__name__}: {str(blad)[:160]}",
        }


def _slad_pobierania(teraz):
    """Czy strony WWW faktycznie były ostatnio pobierane."""
    aktywne = WebsiteSource.objects.filter(is_active=True)
    liczba = aktywne.count()
    if not liczba:
        return {
            "aktywnych_zrodel": 0,
            "wniosek": "brak-danych",
            "opis": "Nie ma aktywnych źródeł WWW, więc nie ma po czym poznać, czy harmonogram działa.",
        }

    ostatnie = aktywne.exclude(last_crawled_at=None).order_by("-last_crawled_at").first()
    if ostatnie is None:
        return {
            "aktywnych_zrodel": liczba,
            "ostatnie_pobranie": None,
            "wniosek": "nie-dziala",
            "opis": f"Jest {liczba} aktywnych źródeł i żadne nie zostało ani razu pobrane.",
        }

    godzin = (teraz - ostatnie.last_crawled_at).total_seconds() / 3600
    dziala = godzin <= PROG_POBIERANIA_H
    return {
        "aktywnych_zrodel": liczba,
        "ostatnie_pobranie": ostatnie.last_crawled_at.isoformat(),
        "godzin_temu": round(godzin, 1),
        "wniosek": "dziala" if dziala else "nie-dziala",
        "opis": (
            f"Ostatnie pobranie {round(godzin, 1)} h temu — harmonogram co 12 h jest dotrzymany."
            if dziala else
            f"Ostatnie pobranie {round(godzin, 1)} h temu, a harmonogram przewiduje co 12 h. "
            f"Beat prawdopodobnie nie chodzi."
        ),
    }


def _slad_retencji(teraz):
    """
    Czy w bazie zalegają rozmowy starsze, niż pozwala polityka klienta.

    Liczymy per klient, bo okres retencji jest jego decyzją, nie naszą.
    Zero zaległych to dowód, że codzienne czyszczenie się wykonuje.
    """
    zalegle = 0
    klientow_z_zaleglosciami = 0

    for tenant in Tenant.objects.filter(data_retention_days__gt=0).only("id", "data_retention_days"):
        prog = teraz - timedelta(days=tenant.data_retention_days)
        # Doba zapasu: zadanie chodzi o 3:30, więc chwilowa zaległość
        # z ostatnich godzin jest normalna, a nie objawem awarii.
        ile = Conversation.objects.filter(
            tenant=tenant, started_at__lt=prog - timedelta(days=1)
        ).count()
        if ile:
            zalegle += ile
            klientow_z_zaleglosciami += 1

    if zalegle == 0:
        return {
            "zaleglych_rozmow": 0,
            "wniosek": "dziala",
            "opis": "Żadna rozmowa nie przekracza okresu retencji swojego klienta.",
        }
    return {
        "zaleglych_rozmow": zalegle,
        "klientow_z_zaleglosciami": klientow_z_zaleglosciami,
        "wniosek": "nie-dziala",
        "opis": (
            f"{zalegle} rozmów przekracza okres retencji u {klientow_z_zaleglosciami} klientów. "
            f"Codzienne czyszczenie RODO się nie wykonuje."
        ),
    }


def _werdykt(broker, pobieranie, retencja):
    """Jedno zdanie, od którego można zacząć działać."""
    slady = [pobieranie["wniosek"], retencja["wniosek"]]

    if "nie-dziala" in slady:
        return (
            "ZADANIA CYKLICZNE NIE DZIAŁAJĄ. Ślady w danych pokazują, że harmonogram "
            "nie był wykonywany. Sprawdź w Render, czy usługi celery-worker i "
            "celery-beat istnieją i są uruchomione — render.yaml je deklaruje, ale "
            "usługi zakładane ręcznie nie powstają z tego pliku."
        )

    if not broker["broker_osiagalny"]:
        return (
            "BROKER NIEOSIĄGALNY z procesu web. Zadania zlecane z żądań wykonują się "
            "wtedy synchronicznie (wolniej, ale działają), a cykliczne nie wykonują się "
            "wcale. Sprawdź zmienną REDIS_URL i czy usługa Redis żyje."
        )

    if broker["odpowiedzialo_workerow"] == 0:
        return (
            "BROKER DZIAŁA, ALE ŻADEN WORKER NIE ODPOWIADA. Kolejka przyjmuje zadania "
            "i nikt ich nie odbiera. Uruchom usługę celery-worker."
        )

    if "brak-danych" in slady:
        return (
            f"Worker odpowiada ({broker['odpowiedzialo_workerow']}), broker działa. "
            "Nie ma jeszcze danych, po których dałoby się potwierdzić harmonogram — "
            "dodaj źródło WWW i sprawdź ponownie po dwunastu godzinach."
        )

    return (
        f"Wszystko działa. Worker odpowiada ({broker['odpowiedzialo_workerow']}), "
        "strony są pobierane zgodnie z harmonogramem, retencja jest dotrzymana."
    )


@extend_schema(
    tags=["Panel — diagnostyka"],
    summary="Czy zadania w tle się wykonują",
    description=(
        "Sprawdza trzy rzeczy naraz: czy broker odpowiada, czy odpowiadają workerzy "
        "oraz — co najważniejsze — czy w danych widać ślady wykonanych zadań "
        "cyklicznych. Brak workera nie powoduje błędów widocznych dla użytkownika, "
        "bo zadania z żądań wykonują się wtedy synchronicznie; cicho przestają "
        "działać tylko zadania z harmonogramu."
    ),
    responses={200: OpenApiResponse(description="Stan zadań w tle i werdykt.")},
)
class DiagnostykaZadanView(APIView):
    """Tylko dla zalogowanego właściciela — pokazuje stan zaplecza."""
    permission_classes = [IsOwnerOrEmployee]

    def get(self, request):
        teraz = timezone.now()
        broker = _stan_brokera()
        pobieranie = _slad_pobierania(teraz)
        retencja = _slad_retencji(teraz)

        try:
            from chatbot_project.celery import app
            harmonogram = sorted(app.conf.beat_schedule.keys())
        except Exception:
            harmonogram = []

        return Response({
            "sprawdzono": teraz.isoformat(),
            "broker_i_workery": broker,
            "zadeklarowany_harmonogram": harmonogram,
            "slady_w_danych": {
                "pobieranie_stron": pobieranie,
                "czyszczenie_rodo": retencja,
            },
            "werdykt": _werdykt(broker, pobieranie, retencja),
        })
