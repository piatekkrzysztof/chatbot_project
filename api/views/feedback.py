from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from chat.models import ChatMessage, ChatFeedback
from rest_framework import status


class SubmitFeedbackView(APIView):
    def post(self, request):
        message_id = request.data.get("message_id")
        is_helpful = request.data.get("is_helpful")

        if message_id is None or is_helpful is None:
            return Response({"error": "Missing data"}, status=400)

        try:
            message = ChatMessage.objects.get(id=message_id, sender="bot")
        except ChatMessage.DoesNotExist:
            raise NotFound("Chat message not found.")

        ChatFeedback.objects.update_or_create(
            message=message,
            defaults={"is_helpful": is_helpful}
        )

        return Response({"status": "success"})
