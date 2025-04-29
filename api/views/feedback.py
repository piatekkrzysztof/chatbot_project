from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from api.serializers import ChatFeedbackSerializer


class SubmitFeedbackView(APIView):

    def post(self, request):
        serializer = ChatFeedbackSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            print(serializer.errors)
            return Response({"status": "success"})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
