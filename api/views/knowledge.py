from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployee


class TenantKnowledgeView(APIView):
    """
    Wiedza firmy wpisywana wprost: opis działalności i regulamin.

    Do tej pory dało się je ustawić wyłącznie w Django adminie, więc klient nie
    miał jak opisać własnej firmy — a bez opisu bot odmawia odpowiedzi na
    najczęstsze pytanie w ogóle ("czym się zajmujecie?"). To osobny widok od
    brandingu widgetu, bo dotyczy tego, co bot wie, a nie jak wygląda.
    """
    permission_classes = [IsOwnerOrEmployee]

    FIELDS = ("gpt_prompt", "regulamin")

    def _serialize(self, tenant):
        return {
            "gpt_prompt": tenant.gpt_prompt or "",
            "regulamin": tenant.regulamin or "",
        }

    def get(self, request):
        return Response(self._serialize(request.user.tenant))

    def patch(self, request):
        tenant = request.user.tenant
        changed = []

        for field in self.FIELDS:
            if field in request.data:
                setattr(tenant, field, request.data[field] or "")
                changed.append(field)

        if changed:
            tenant.save(update_fields=changed)

        return Response(self._serialize(tenant))
