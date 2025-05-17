from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwner(BasePermission):
    """
    Pozwala tylko użytkownikom z rolą 'owner'.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.role == 'owner')


class IsOwnerOrEmployee(BasePermission):
    """
    Pozwala użytkownikom z rolą 'owner' lub 'employee'.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.role in ['owner', 'employee'])


class IsTenantMember(BasePermission):
    """
    Użytkownik musi należeć do tenantowego systemu (czyli dowolna rola).
    Można stosować jako ogólne sprawdzenie obecności w systemie.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and hasattr(request.user, 'tenant'))


class ReadOnlyOrOwner(BasePermission):
    """
    Tylko właściciele mogą modyfikować dane, reszta ma dostęp tylko do odczytu.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.role == 'owner')
