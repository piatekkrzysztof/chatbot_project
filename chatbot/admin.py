from django.contrib import admin
from .models import ChatMessage, FAQ, WebsiteSettings


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'message', 'timestamp')
    list_filter = ('sender', 'timestamp')
    search_fields = ('message',)


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'answer')
    search_fields = ('question', 'answer')


@admin.register(WebsiteSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    list_display = ['website_name', 'owner_email']