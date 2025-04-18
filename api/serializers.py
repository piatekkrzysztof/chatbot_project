from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import CustomUser, Tenant, InvitationToken
from chat.models import PromptLog, ChatMessage
from documents.models import Document, DocumentChunk


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'role', 'tenant', 'is_active', 'last_login'
        ]
        read_only_fields = ['id', 'tenant', 'last_login']


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    conversation_id = serializers.CharField()


class ChatResponseSerializer(serializers.Serializer):
    response = serializers.CharField()


class WidgetSettingsSerializer(serializers.Serializer):
    widget_position = serializers.CharField()
    widget_color = serializers.CharField()
    widget_title = serializers.CharField()


class RegisterSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def create(self, validated_data):
        tenant = Tenant.objects.create(
            name=validated_data['company_name'],
            owner_email=validated_data['email'],
        )
        user = CustomUser.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            tenant=tenant,
            role='owner',
        )
        return user

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = {
            'id': self.user.id,
            'email': self.user.email,
            'role': self.user.role,
            'tenant_id': self.user.tenant_id,
            'tenant_name': self.user.tenant.name,
        }

        return data


class InvitationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvitationToken
        fields = ['email', 'role', 'duration_hours', 'max_uses']

    def create(self, validated_data):
        tenant = self.context['request'].user.tenant
        return InvitationToken.objects.create(tenant=tenant, **validated_data)


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            invitation = InvitationToken.objects.get(token=attrs['token'])
        except InvitationToken.DoesNotExist:
            raise serializers.ValidationError("Invalid token.")

        if not invitation.is_valid():
            raise serializers.ValidationError("Token expired or used up.")

        attrs['invitation'] = invitation
        return attrs

    def create(self, validated_data):
        invitation = validated_data['invitation']
        tenant = invitation.tenant

        user = CustomUser.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            tenant=tenant,
            role=invitation.role
        )

        invitation.use()
        return user


class DocumentSerializer(serializers.ModelSerializer):
    chunk_count = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    preview = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "name",
            "processed",
            "uploaded_at",
            "chunk_count",
            "status",
            "preview",
        ]

    def get_chunk_count(self, obj):
        return obj.chunks.count()

    def get_status(self, obj):
        if obj.processed:
            if obj.chunks.exists():
                return "ready"
            return "processed_no_chunks"
        return "processing"

    def get_preview(self, obj):
        return obj.content[:500] if obj.content else ""


class DocumentChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentChunk
        fields = ["id", "content", "created_at"]
        read_only_fields = fields


class PromptLogSerializer(serializers.ModelSerializer):
    is_helpful = serializers.SerializerMethodField()

    class Meta:
        model = PromptLog
        fields = [
            "id", "prompt", "response", "model", "source",
            "tokens", "created_at", "is_helpful", "conversation_id"
        ]

    def get_is_helpful(self, obj):
        msg = ChatMessage.objects.filter(
            conversation=obj.conversation,
            sender="bot",
            message=obj.response
        ).first()
        if msg and hasattr(msg, "feedback"):
            return msg.feedback.is_helpful
        return None
