from django.contrib import admin
from .models import Document, WebsiteSource


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'name', 'uploaded_at')
    list_filter = ('tenant', 'uploaded_at')
    search_fields = ('title',)


@admin.register(WebsiteSource)
class WebsiteSourceAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'name', 'url', 'is_active', 'created_at')
    list_filter = ('tenant', 'is_active')
    search_fields = ('name', 'url')
