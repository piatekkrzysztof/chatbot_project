from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsOwner(BasePermission):
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
            request.user
            and getattr(request.user, "is_authenticated", False)
            and getattr(request.user, "role", None) == "owner"
        )


class IsOwnerOrEmployee(BasePermission):
    """
    Pozwala użytkownikom z rolą 'owner' lub 'employee'.
    """

    def has_permission(self, request, view):
        return bool(
            hasattr(request, "user")
            and hasattr(request.user, "role")
            and request.user.role in ["owner", "employee"]
        )


class IsTenantMember(BasePermission):
    """
    Użytkownik musi należeć do tenantowego systemu (czyli dowolna rola).
    Można stosować jako ogólne sprawdzenie obecności w systemie.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and hasattr(request.user, "tenant")
        )


class IsOwnerOrEmployeeOrTenantReadOnly(BasePermission):
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
        uzytkownik = getattr(request, "user", None)
        if not (uzytkownik and getattr(uzytkownik, "is_authenticated", False)):
            return False
        if not getattr(uzytkownik, "tenant_id", None):
            return False
        if request.method in SAFE_METHODS:
            return True
        return getattr(uzytkownik, "role", None) in ("owner", "employee")
