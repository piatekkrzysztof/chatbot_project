from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.tenancy import verified_request_tenant


class IsTenantMember(BasePermission):
    """Aktywny użytkownik i zgodna, wcześniej ustalona firma żądania."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and getattr(user, "tenant_id", None)
            and verified_request_tenant(request)
        )


class IsOwner(IsTenantMember):
    """
    Pozwala tylko użytkownikom z rolą 'owner'.
    """

    def has_permission(self, request, view):
        # getattr, a nie request.user.role: AnonymousUser nie ma pola `role`,
        # więc niezalogowane żądanie wywracało widok błędem 500 zamiast
        # zwrócić odmowę. Poza złym kodem odpowiedzi zaśmiecało to logi
        # wyjątkami przy każdym przypadkowym wejściu bota z internetu.
        # IsOwnerOrEmployee obok zabezpiecza się przed tym od dawna.
        return bool(
            super().has_permission(request, view) and getattr(request.user, "role", None) == "owner"
        )


class IsOwnerOrEmployee(IsTenantMember):
    """
    Pozwala użytkownikom z rolą 'owner' lub 'employee'.
    """

    def has_permission(self, request, view):
        return bool(
            super().has_permission(request, view) and request.user.role in ["owner", "employee"]
        )


class IsOwnerOrEmployeeOrTenantReadOnly(IsTenantMember):
    """
    Zapis dla właściciela i pracownika, odczyt dla każdego członka firmy.

    Rola `viewer` istniała, ale nie miała czego oglądać: widoki bazy wiedzy,
    ustawień widgetu, prywatności i diagnostyki trzymały IsOwnerOrEmployee na
    całej klasie, razem z metodą GET. Obserwator, który nie może obserwować,
    to nie jest polityka bezpieczeństwa, tylko przeoczenie — zwłaszcza że
    rozmowy klientów, czyli najwrażliwsze dane w systemie, `viewer` czytał
    od zawsze przez /api/chat/logs/.

    Odczyt jest tu ZAWĘŻONY do zalogowanych członków firmy. To celowo NIE jest
    zachowanie DRF-owego IsAuthenticatedOrReadOnly, które przy metodzie
    bezpiecznej przepuszcza kogokolwiek — poprzednik tej klasy (ReadOnlyOrOwner)
    miał dokładnie taką dziurę i dlatego został usunięty zamiast poprawiony.

    Nie stosujemy tego wszędzie. Poza zasięgiem `viewera` zostają rzeczy,
    przy których sam odczyt jest osobnym ryzykiem: hurtowy eksport rozmów do
    CSV, lista kont i zaproszeń oraz dane rozliczeniowe.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in ("owner", "employee")
