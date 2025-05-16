from rest_framework import viewsets, permissions
from accounts.models import CustomUser
from api.serializers import UserSerializer
from rest_framework.exceptions import PermissionDenied
from api.utils.mixins import TenantQuerysetMixin


class UserViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = CustomUser.objects.all()

    def perform_create(self, serializer):
        if not self.request.user.role == 'owner':
            raise PermissionDenied("Only owners can create users.")
        serializer.save(tenant=self.request.user.tenant)

    def perform_destroy(self, instance):
        if not self.request.user.role == 'owner':
            raise PermissionDenied("Only owners can delete users.")
        instance.delete()
