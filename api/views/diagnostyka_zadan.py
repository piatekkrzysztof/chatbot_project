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
from api.permissions import IsOwnerOrEmployee, IsOwnerOrEmployeeOrTenantReadOnly
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


def _slad_pobierania(teraz, tenant):
    """
    Czy strony WWW faktycznie były ostatnio pobierane.

    Zawężone do jednego klienta. Endpoint jest dostępny dla każdego
    właściciela konta, a nie tylko dla nas — bez tego filtra klient widziałby
    liczbę źródeł innych firm, a w przykładzie błędu nawet cudzy adres strony.
    """
    aktywne = WebsiteSource.objects.filter(is_active=True, tenant=tenant)
    liczba = aktywne.count()
    if not liczba:
        return {
            "aktywnych_zrodel": 0,
            "wniosek": "brak-danych",
            "opis": "Nie ma aktywnych źródeł WWW, więc nie ma po czym poznać, czy harmonogram działa.",
        }

    ostatnie = aktywne.exclude(last_crawled_at=None).order_by("-last_crawled_at").first()
    if ostatnie is None:
        # Rozróżniamy dwie sytuacje, które wyglądają identycznie w polu
        # last_crawled_at, a wymagają czegoś innego: zadanie nigdy nie ruszyło
        # (nikt go nie zlecił) kontra ruszyło i się wywróciło.
        z_bledem = list(aktywne.exclude(last_error="").values_list("name", "last_error")[:3])
        probowane = aktywne.exclude(last_attempt_at=None).count()

        if z_bledem:
            nazwa, tresc = z_bledem[0]
            return {
                "aktywnych_zrodel": liczba,
                "ostatnie_pobranie": None,
                "zrodel_z_bledem": len(z_bledem),
                "przyklad_bledu": f"{nazwa}: {tresc[:200]}",
                "wniosek": "nie-dziala",
                "opis": (
                    f"Pobieranie było próbowane i zakończyło się błędem. "
                    f"To usterka crawlera albo samej strony, nie zaplecza."
                ),
            }

        if probowane == 0:
            return {
                "aktywnych_zrodel": liczba,
                "ostatnie_pobranie": None,
                "wniosek": "nie-probowano",
                "opis": (
                    f"Jest {liczba} aktywnych źródeł i żadnego nie próbowano jeszcze pobrać. "
                    f"Zadanie nigdy nie zostało zlecone — kliknij „Odśwież teraz” w panelu "
                    f"albo poczekaj na najbliższy przebieg harmonogramu."
                ),
            }

        return {
            "aktywnych_zrodel": liczba,
            "ostatnie_pobranie": None,
            "wniosek": "nie-dziala",
            "opis": f"Próbowano pobrać {probowane} źródeł, żadne się nie udało i nie zapisano błędu.",
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
            if dziala
            else f"Ostatnie pobranie {round(godzin, 1)} h temu, a harmonogram przewiduje co 12 h. "
            f"Beat prawdopodobnie nie chodzi."
        ),
    }


def _slad_retencji(teraz, tenant_zadania):
    """
    Czy w bazie zalegają rozmowy starsze, niż pozwala polityka klienta.

    Liczymy per klient, bo okres retencji jest jego decyzją, nie naszą.
    Zero zaległych to dowód, że codzienne czyszczenie się wykonuje.
    """
    zalegle = 0
    klientow_z_zaleglosciami = 0
    ktokolwiek_dobil_do_progu = False

    # Tylko własne dane klienta — z tego samego powodu co przy pobieraniu.
    klienci = Tenant.objects.filter(pk=tenant_zadania.pk, data_retention_days__gt=0)
    for tenant in klienci.only("id", "data_retention_days"):
        prog = teraz - timedelta(days=tenant.data_retention_days)
        # Doba zapasu: zadanie chodzi o 3:30, więc chwilowa zaległość
        # z ostatnich godzin jest normalna, a nie objawem awarii.
        ile = Conversation.objects.filter(
            tenant=tenant, started_at__lt=prog - timedelta(days=1)
        ).count()
        if ile:
            zalegle += ile
            klientow_z_zaleglosciami += 1

        # Czy ten klient w ogóle zbliżył się do swojego progu retencji.
        # Bez tego brak zaległości znaczyłby „czyszczenie działa" także wtedy,
        # gdy najstarsza rozmowa ma tydzień przy retencji 90 dni — czyli gdy
        # nie było jeszcze czego kasować.
        blisko_progu = teraz - timedelta(days=tenant.data_retention_days * 0.8)
        if Conversation.objects.filter(tenant=tenant, started_at__lt=blisko_progu).exists():
            ktokolwiek_dobil_do_progu = True

    if zalegle == 0 and not ktokolwiek_dobil_do_progu:
        return {
            "zaleglych_rozmow": 0,
            "wniosek": "brak-danych",
            "opis": (
                "Żadna rozmowa nie zbliżyła się jeszcze do okresu retencji, "
                "więc nie ma czego kasować — brak zaległości nie dowodzi, "
                "że czyszczenie działa."
            ),
        }

    if zalegle == 0:
        return {
            "zaleglych_rozmow": 0,
            "wniosek": "dziala",
            "opis": "Są rozmowy w okolicy progu retencji i żadna go nie przekracza.",
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


def _poziom(broker, pobieranie, retencja):
    """
    Powaga stanu w jednym słowie, wyliczana po stronie serwera.

    Panel mógłby to wywnioskować sam z pozostałych pól, ale wtedy istniałyby
    dwie definicje tego, co znaczy „awaria" — tu i w przeglądarce — i prędzej
    czy później by się rozjechały. Kolejność warunków musi odpowiadać
    kolejności w _werdykt, żeby kolor zgadzał się z treścią.
    """
    slady = [pobieranie["wniosek"], retencja["wniosek"]]

    if "nie-dziala" in slady:
        return "awaria"
    if not broker["broker_osiagalny"] or broker["odpowiedzialo_workerow"] == 0:
        return "awaria"
    if "nie-probowano" in slady or "brak-danych" in slady:
        return "uwaga"
    return "ok"


def _werdykt(broker, pobieranie, retencja):
    """
    Jedno zdanie, od którego można zacząć działać.

    Składane z obu sygnałów osobno, a nie z jednej wspólnej gałęzi. Wcześniej
    komunikat „brak danych" był zaszyty pod pobieranie stron, więc gdy danych
    brakowało retencji, werdykt kazał dodać źródło WWW — komuś, kto miał trzy
    i właśnie je pobrał. Diagnostyka, która myli sygnały, kieruje w złe miejsce.
    """
    sygnaly = (("pobieranie stron", pobieranie), ("czyszczenie RODO", retencja))

    # 1. Awarie mają pierwszeństwo i muszą wskazywać właściwą przyczynę:
    #    stare pobieranie to zegar, zaległe rozmowy to zadanie czyszczące,
    #    zapisany błąd crawlera to ani jedno, ani drugie.
    zepsute = [(nazwa, s) for nazwa, s in sygnaly if s["wniosek"] == "nie-dziala"]
    if zepsute:
        nazwa, sygnal = zepsute[0]
        if sygnal.get("przyklad_bledu"):
            return (
                f"POBIERANIE STRON KOŃCZY SIĘ BŁĘDEM. {sygnal['przyklad_bledu']} "
                "To usterka crawlera albo samej strony — usługi na Renderze działają, "
                "więc nie ma tam czego naprawiać."
            )
        return (
            f"NIE DZIAŁA: {nazwa}. {sygnal['opis']} Sprawdź w Render, czy usługa "
            "celery-worker istnieje i jest uruchomiona — plik render.yaml ją "
            "deklaruje, ale usługi zakładane ręcznie nie powstają z tego pliku."
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

    # Dopiero tutaj, PO sprawdzeniu brokera i workera. Wcześniej ta gałąź stała
    # wyżej i potrafiła oznajmić „zaplecze działa (worker odpowiada: 0)" —
    # zdanie wewnętrznie sprzeczne, w dodatku niezgodne z polem `poziom`,
    # które w tej samej sytuacji zwracało awarię.
    if pobieranie["wniosek"] == "nie-probowano":
        return (
            f"Zaplecze działa (worker odpowiada: {broker['odpowiedzialo_workerow']}), ale "
            "żadnego źródła WWW nie próbowano jeszcze pobrać. To nie jest awaria — "
            "zadanie po prostu nie zostało jeszcze zlecone. Kliknij „Odśwież teraz” "
            "przy źródłach w panelu albo poczekaj na najbliższy przebieg harmonogramu."
        )

    # 2. Nic nie jest zepsute. Zostaje pytanie, ile z tego umiemy potwierdzić —
    #    i tu trzeba nazwać konkretny sygnał, a nie mówić ogólnie „brak danych".
    potwierdzone = [nazwa for nazwa, s in sygnaly if s["wniosek"] == "dziala"]
    niepotwierdzone = [nazwa for nazwa, s in sygnaly if s["wniosek"] == "brak-danych"]

    if not niepotwierdzone:
        return (
            f"Wszystko działa. Worker odpowiada ({broker['odpowiedzialo_workerow']}), "
            "strony są pobierane zgodnie z harmonogramem, retencja jest dotrzymana."
        )

    czesci = [f"Zaplecze działa (worker odpowiada: {broker['odpowiedzialo_workerow']})."]
    if potwierdzone:
        czesci.append(f"Potwierdzone: {', '.join(potwierdzone)}.")
    czesci.append(
        f"Nie da się jeszcze potwierdzić: {', '.join(niepotwierdzone)} — "
        + " ".join(s["opis"] for nazwa, s in sygnaly if s["wniosek"] == "brak-danych")
    )
    return " ".join(czesci)


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

    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]

    def get(self, request):
        teraz = timezone.now()
        broker = _stan_brokera()
        pobieranie = _slad_pobierania(teraz, request.tenant)
        retencja = _slad_retencji(teraz, request.tenant)

        try:
            from chatbot_project.celery import app

            harmonogram = sorted(app.conf.beat_schedule.keys())
        except Exception:
            harmonogram = []

        return Response(
            {
                "sprawdzono": teraz.isoformat(),
                "broker_i_workery": broker,
                "zadeklarowany_harmonogram": harmonogram,
                "slady_w_danych": {
                    "pobieranie_stron": pobieranie,
                    "czyszczenie_rodo": retencja,
                },
                # Dwa sygnały o tym, co widzi klient, a nie o zapleczu. Poziom
                # ogólny ich nie obejmuje: niepełna podstrona nie znaczy, że system
                # nie działa, tylko że wiedza jest uboższa, niż się wydaje.
                "baza_wiedzy": _zdrowie_bazy_wiedzy(request.tenant),
                "poczta": _zdrowie_poczty(request.tenant),
                "poziom": _poziom(broker, pobieranie, retencja),
                "werdykt": _werdykt(broker, pobieranie, retencja),
            }
        )


# Poniżej którego udziału wyciągniętej treści uznajemy podstronę za niepełną.
# Wartość z pomiaru: strona główna klienta dawała 3%, "/o-nas" 20%, a "/cennik",
# który wyszedł dobrze — 73%. Połowa oddziela te przypadki z zapasem po obu
# stronach i nie krzyczy przy stronach, które po prostu mają dużo nawigacji.
PROG_NIEPELNEJ_STRONY = 0.5


def _zdrowie_bazy_wiedzy(tenant):
    """
    Czy wiedza, którą klient wgrał, faktycznie trafiła do bota.

    Powstało z przypadku, który trwał tygodniami i nie było go po czym poznać:
    strona główna miała w bazie 257 znaków z 10 037, a panel pokazywał zielone
    „gotowe". Status mówił prawdę — dokument BYŁ przetworzony. Tyle że pusty.

    Dwa sygnały. „Bez fragmentów" to awaria: treść jest, wektory się nie
    policzyły, bot tego nie zna mimo zielonego statusu. „Niepełne" to
    ostrzeżenie: ze strony wyciągnęliśmy mniejszość tego, co na niej widać.
    """
    from documents.models import Document, DocumentChunk

    dokumenty = list(
        Document.objects.filter(tenant=tenant, uzywaj_w_wyszukiwaniu=True)
        .exclude(content="")
        .only("id", "name", "content", "znakow_na_stronie")
    )
    z_fragmentami = set(
        DocumentChunk.objects.filter(document__tenant=tenant)
        .values_list("document_id", flat=True)
        .distinct()
    )

    bez_fragmentow = [d.name for d in dokumenty if d.id not in z_fragmentami]

    niepelne = []
    for dokument in dokumenty:
        widocznych = dokument.znakow_na_stronie
        # Bez mianownika nie da się orzec niczego. Dotyczy wgranych plików
        # (nie ma strony, z którą można porównać) i podstron pobranych przed
        # wprowadzeniem tej miary — te ocenimy przy najbliższym odświeżeniu.
        if not widocznych:
            continue
        udzial = len(dokument.content) / widocznych
        if udzial < PROG_NIEPELNEJ_STRONY:
            niepelne.append({"nazwa": dokument.name, "udzial_procent": round(udzial * 100)})

    niepelne.sort(key=lambda p: p["udzial_procent"])

    if bez_fragmentow:
        wniosek, opis = (
            "nie-dziala",
            (
                f"{len(bez_fragmentow)} dokumentów ma treść, ale nie ma policzonych "
                "fragmentów — bot ich nie zna, mimo że w bazie wiedzy wyglądają na gotowe."
            ),
        )
    elif niepelne:
        wniosek, opis = (
            "ostrzezenie",
            (
                f"Z {len(niepelne)} podstron wyciągnęliśmy mniejszość widocznej treści. "
                "Bot zna tylko tę część. Zwykle znaczy to, że strona jest budowana "
                "w sposób utrudniający odczyt treści."
            ),
        )
    elif not dokumenty:
        wniosek, opis = "brak-danych", "Baza wiedzy jest pusta — bot nie ma z czego odpowiadać."
    else:
        wniosek, opis = "dziala", f"Wszystkie {len(dokumenty)} dokumentów ma policzone fragmenty."

    return {
        "wniosek": wniosek,
        "opis": opis,
        "dokumentow": len(dokumenty),
        "bez_fragmentow": bez_fragmentow[:10],
        "niepelne": niepelne[:10],
    }


def _zdrowie_poczty(tenant):
    """
    Czy powiadomienia mają jak wyjść.

    Klient nie dowie się o zepsutej poczcie inaczej niż przegapiając zapytanie.
    Sprawdzamy kształt konfiguracji (to samo, co przy starcie procesu) oraz
    ślad po ostatnich próbach wysyłki.
    """
    from django.conf import settings

    from chat.kontrola_poczty import problemy_z_konfiguracja
    from chat.models import ContactRequest

    problemy = problemy_z_konfiguracja(settings)
    nieudane = list(
        ContactRequest.objects.filter(tenant=tenant)
        .exclude(blad_powiadomienia="")
        .order_by("-created_at")
        .values_list("blad_powiadomienia", flat=True)[:5]
    )

    if not tenant.owner_email:
        wniosek, opis = (
            "ostrzezenie",
            (
                "Nie ma adresu, na który wysyłamy powiadomienia. Zapytania zobaczysz "
                "wyłącznie po zalogowaniu do panelu."
            ),
        )
    elif problemy:
        wniosek, opis = "nie-dziala", f"Konfiguracja poczty: {problemy[0]}"
    elif nieudane:
        wniosek, opis = (
            "ostrzezenie",
            (
                f"Ostatnie {len(nieudane)} powiadomień nie doszło. Problem jest po stronie "
                "poczty, nie Twojego konta."
            ),
        )
    else:
        wniosek, opis = "dziala", f"Powiadomienia wychodzą na {tenant.owner_email}."

    return {"wniosek": wniosek, "opis": opis, "adres": tenant.owner_email or ""}
