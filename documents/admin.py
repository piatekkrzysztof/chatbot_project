from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'name', 'uploaded_at')
    list_filter = ('tenant', 'uploaded_at')
    search_fields = ('title',)
