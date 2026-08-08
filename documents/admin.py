from django.contrib import admin
from .models import Document, WebsiteSource


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'name', 'processed', 'uploaded_at')
    list_filter = ('tenant', 'processed', 'uploaded_at')
    # 'title' nie istnieje w modelu od migracji 0002 — wyszukiwanie rzucało FieldError
    search_fields = ('name', 'content')


@admin.register(WebsiteSource)
class WebsiteSourceAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'name', 'url', 'is_active', 'created_at')
    list_filter = ('tenant', 'is_active')
    search_fields = ('name', 'url')
