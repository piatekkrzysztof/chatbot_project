from django.contrib import admin
from .models import ChatMessage, FAQ, Tenant, Conversation

admin.site.register(Tenant)
admin.site.register(FAQ)
admin.site.register(Conversation)
admin.site.register(ChatMessage)
