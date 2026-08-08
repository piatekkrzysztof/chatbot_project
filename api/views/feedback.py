from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from api.serializers import ChatFeedbackSerializer
from api.permissions import IsTenantMember
from drf_spectacular.utils import extend_schema

from api.schemas import ErrorSerializer, StatusSerializer


@extend_schema(
    tags=["Panel — czat"],
    summary="Oceń odpowiedź bota",
    request=ChatFeedbackSerializer,
    responses={200: StatusSerializer, 400: ErrorSerializer},
)
class SubmitFeedbackView(APIView):
    permission_classes = [IsTenantMember]

    def post(self, request):
        serializer = ChatFeedbackSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success"})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
