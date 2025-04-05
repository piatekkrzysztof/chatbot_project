from django.contrib import admin
from .models import ChatMessage, FAQ, Tenant, Conversation


# @admin.register(Tenant)
# class TenantAdmin(admin.ModelAdmin):
#     list_display = ('name', 'owner_email', 'widget_position', 'widget_color', 'widget_title')
#
#
# admin.site.register(FAQ)
# admin.site.register(Conversation)
# admin.site.register(ChatMessage)
