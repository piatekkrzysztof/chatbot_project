from rest_framework import serializers

from accounts.models import CustomUser
from documents.models import Document


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'tenant', 'role']


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    conversation_id = serializers.CharField()


class ChatResponseSerializer(serializers.Serializer):
    response = serializers.CharField()


class WidgetSettingsSerializer(serializers.Serializer):
    widget_position = serializers.CharField()
    widget_color = serializers.CharField()
    widget_title = serializers.CharField()


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ['id', 'title', 'file', 'uploaded_at', 'content']
        read_only_fields = ['uploaded_at', 'content']
