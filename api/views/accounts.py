from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from accounts.models import InvitationToken
from api.serializers import RegisterSerializer, UserSerializer, AcceptInvitationSerializer

from rest_framework_simplejwt.views import TokenObtainPairView
from api.serializers import CustomTokenObtainPairSerializer

from rest_framework import generics, permissions
from api.serializers import InvitationCreateSerializer
from rest_framework.exceptions import PermissionDenied
from api.utils.mixins import TenantQuerysetMixin
from rest_framework.generics import ListAPIView
from api.permissions import *


class RegisterView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Account created successfully'}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = []


class MeView(APIView):
    premission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        data = UserSerializer(user).data
        return Response(data)


class CreateInvitationView(generics.CreateAPIView):
    serializer_class = InvitationCreateSerializer
    permission_classes = [IsOwner]

    def perform_create(self, serializer):
        if self.request.user.role != 'owner':
            raise PermissionDenied("Only owners can invite users.")
        serializer.save()


class AcceptInvitationView(APIView):
    def post(self, request):
        serializer = AcceptInvitationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User registered successfully."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InvitationListView(TenantQuerysetMixin, ListAPIView):
    permission_classes = [IsOwner]
    serializer_class = InvitationCreateSerializer
    queryset = InvitationToken.objects.all()
