from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployeeOrTenantReadOnly
from api.schemas import KnowledgeSerializer
from api.utils.zadania import dane_obiektu
from documents.file_limits import ZNAKI_STERUJACE

#: Sufit techniczny, nie produktowy: prompt i tak mieści kilkanaście tysięcy
#: znaków wiedzy, a regulamin na 30 tys. znaków jest u klientów normalny.
MAKS_ZNAKOW_POLA = 200_000


@extend_schema(
    tags=["Panel — baza wiedzy"],
    summary="Opis działalności i regulamin",
    description=(
        "Opis działalności to główne źródło wiedzy bota. Bez niego bot odmawia "
        "odpowiedzi nawet na pytanie, czym firma się zajmuje."
    ),
    request=KnowledgeSerializer,
    responses={200: KnowledgeSerializer},
)
class TenantKnowledgeView(APIView):
    """
    Wiedza firmy wpisywana wprost: opis działalności i regulamin.

    Do tej pory dało się je ustawić wyłącznie w Django adminie, więc klient nie
    miał jak opisać własnej firmy — a bez opisu bot odmawia odpowiedzi na
    najczęstsze pytanie w ogóle ("czym się zajmujecie?"). To osobny widok od
    brandingu widgetu, bo dotyczy tego, co bot wie, a nie jak wygląda.
    """

    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]

    FIELDS = ("gpt_prompt", "regulamin")

    def _serialize(self, tenant):
        return {
            "gpt_prompt": tenant.gpt_prompt or "",
            "regulamin": tenant.regulamin or "",
        }

    @staticmethod
    def _tekst(field, wartosc):
        """
        Wartość pola jako tekst gotowy do zapisu - albo 400.

        Do 2.32.18 wartość szła do modelu wprost: lista zapisywała się jako
        swój zapis w Pythonie, znak NUL kończył żądanie błędem bazy (500),
        a długości nie ograniczało nic poza limitem treści żądania. Oba pola
        wchodzą do promptu przy każdej wiadomości i wczytują się z firmą przy
        każdym żądaniu, więc megabajtowy tekst kosztuje wszystkich.
        """
        if wartosc is None:
            return ""
        if not isinstance(wartosc, str):
            raise ValidationError({field: "To pole musi być tekstem."})
        wartosc = ZNAKI_STERUJACE.sub("", wartosc)
        if len(wartosc) > MAKS_ZNAKOW_POLA:
            raise ValidationError(
                {field: f"Tekst jest za długi (najwyżej {MAKS_ZNAKOW_POLA} znaków)."}
            )
        return wartosc

    def get(self, request):
        return Response(self._serialize(request.user.tenant))

    def patch(self, request):
        tenant = request.user.tenant
        dane = dane_obiektu(request)
        changed = []

        for field in self.FIELDS:
            if field in dane:
                setattr(tenant, field, self._tekst(field, dane[field]))
                changed.append(field)

        if changed:
            tenant.save(update_fields=changed)

        return Response(self._serialize(tenant))
