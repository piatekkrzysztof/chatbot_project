# from django.contrib import admin
# from .models import Conversation, ChatMessage, ChatUsageLog, FAQ
#
#
# @admin.register(Conversation)
# class ConversationAdmin(admin.ModelAdmin):
#     list_display = ('tenant', 'user_identifier', 'started_at')
#     list_filter = ('tenant', 'started_at')
#
#
# @admin.register(ChatMessage)
# class ChatMessageAdmin(admin.ModelAdmin):
#     list_display = ('conversation', 'sender', 'message', 'timestamp')
#     list_filter = ('conversation__tenant', 'sender')
#
#
# @admin.register(ChatUsageLog)
# class ChatUsageLogAdmin(admin.ModelAdmin):
#     list_display = ('tenant', 'tokens_used', 'created_at')
#     list_filter = ('tenant', 'created_at')
#
#
# @admin.register(FAQ)
# class FAQAdmin(admin.ModelAdmin):
#     list_display = ('tenant', 'question', 'answer')
#     list_filter = ('tenant',)
#     search_fields = ('question', 'answer')
