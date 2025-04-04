from django.contrib import admin
from .models import Tenant

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_key', 'owner_email', 'widget_position', 'widget_color', 'widget_title', 'openai_api_key')
    search_fields = ('name', 'owner_email', 'api_key')
