from django.contrib import admin
from .models import Tenant, CustomUser, InvitationToken


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "gpt_prompt", "subscription_status", "current_token_usage", "token_limit")
    search_fields = ("name",)
    readonly_fields = ("api_key", "created_at")


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "tenant", "role")
    list_filter = ("role", "tenant")


@admin.register(InvitationToken)
class InvitationTokenAdmin(admin.ModelAdmin):
    list_display = ("email", "tenant", "role", "duration", "users", "max_users", "is_valid_token", "expires_at")
    readonly_fields = ("token", "created_at", "expires_at")
    list_filter = ("role", "duration")

    def is_valid_token(self, obj):
        return obj.is_valid()

    is_valid_token.boolean = True
