from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Tenant
from django.utils.translation import gettext_lazy as _


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = (
    'name', 'api_key', 'owner_email', 'widget_position', 'widget_color', 'widget_title', 'openai_api_key')
    search_fields = ('name', 'owner_email', 'api_key')


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'first_name', 'last_name', 'tenant', 'role', 'is_staff')
    list_filter = ('tenant', 'role', 'is_staff', 'is_active')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'email')}),
        (_('Permissions'), {'fields': ('tenant', 'role', 'is_staff', 'is_active')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )


admin.site.register(CustomUser, CustomUserAdmin)
